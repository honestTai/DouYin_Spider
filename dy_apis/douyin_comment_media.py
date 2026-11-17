import io
import json
import urllib.parse
import zlib
from pathlib import Path

from PIL import Image

from builder.header import HeaderBuilder, HeaderType
from builder.params import Params
from dy_apis.douyin_api import check_risk_response
from dy_apis.douyin_creator_api import _gateway_headers, _imagex_random_s
from utils import http_client as requests
from utils.imagex_sign import IMAGEX_HOST, sign_request


COMMENT_UPLOAD_AUTH_PATH = "/aweme/v1/web/comment/upload/auth/"
DEFAULT_IMAGE_SERVICE_ID = "c9aec8xkvj"
IMAGE_APP_ID = "6383"
IMAGE_ORIGIN = "https://www.douyin.com"
MAX_IMAGE_SIZE = 10 * 1024 * 1024


def _image_bytes(image):
    if isinstance(image, (str, Path)):
        data = Path(image).read_bytes()
    else:
        data = bytes(image)
    if not data:
        raise ValueError("图片内容为空")
    if len(data) > MAX_IMAGE_SIZE:
        raise ValueError("图片评论文件不能超过 10MB")
    with Image.open(io.BytesIO(data)) as source:
        width, height = source.size
        image_format = (source.format or "").lower()
    if width > 10000 or height > 10000:
        raise ValueError("图片宽高不能超过 10000 像素")
    if image_format not in {"png", "jpeg", "webp", "bmp"}:
        raise ValueError("图片评论只支持 png、jpeg、webp、bmp")
    return data, width, height, image_format


def get_comment_upload_auth(auth, proxies=None):
    referer = f"{IMAGE_ORIGIN}/"
    headers = HeaderBuilder.build(HeaderType.GET)
    headers.set_referer(referer)
    params = Params().with_platform(auth=auth, url=referer)
    params.add_param("content_type", 0)
    params.with_a_bogus()
    response = requests.get(
        f"{IMAGE_ORIGIN}{COMMENT_UPLOAD_AUTH_PATH}",
        headers=headers.get(), params=params.get(), cookies=auth.cookie,
        verify=False, proxies=proxies,
    )
    check_risk_response(response)
    payload = response.json()
    if payload.get("status_code") not in (0, "0"):
        raise RuntimeError(f"获取评论图片上传凭证失败: {payload}")
    required = ("access_key", "secret_key", "session_token")
    if any(not payload.get(name) for name in required):
        raise RuntimeError(f"评论图片上传凭证字段缺失: {payload}")
    return {
        "AccessKeyID": payload["access_key"],
        "SecretAccessKey": payload["secret_key"],
        "SessionToken": payload["session_token"],
        "service_id": payload.get("service_id") or DEFAULT_IMAGE_SERVICE_ID,
    }


def _apply(auth, sts, user_id, service_id, proxies=None):
    query = {
        "Action": "ApplyImageUpload",
        "Version": "2018-08-01",
        "ServiceId": service_id,
        "app_id": IMAGE_APP_ID,
        "user_id": str(user_id),
        "s": _imagex_random_s(label="comment_image_apply_s"),
    }
    signed = sign_request(
        sts["AccessKeyID"], sts["SecretAccessKey"], sts["SessionToken"],
        method="GET", query_params=query, body=b"",
    )
    response = requests.get(
        f"https://{IMAGEX_HOST}/", headers=_gateway_headers(signed),
        params=query, verify=False, proxies=proxies,
    )
    payload = response.json()
    result = payload.get("Result") or {}
    address = result.get("UploadAddress") or {}
    stores = address.get("StoreInfos") or []
    hosts = address.get("UploadHosts") or []
    if not stores or not hosts:
        raise RuntimeError(f"评论图片 ApplyImageUpload 失败: {payload}")
    return {
        "store_uri": stores[0]["StoreUri"],
        "auth": stores[0]["Auth"],
        "upload_host": hosts[0],
        "session_key": address["SessionKey"],
    }


def _upload_bytes(auth, node, data, user_id, proxies=None):
    headers = {
        "authorization": node["auth"],
        "referer": f"{IMAGE_ORIGIN}/",
        "user-agent": HeaderBuilder.ua,
        "x-storage-u": urllib.parse.quote(str(user_id)),
        "content-crc32": f"{zlib.crc32(data) & 0xffffffff:08x}",
        "content-type": "application/octet-stream",
        "content-disposition": 'attachment; filename="undefined"',
        "accept": "*/*",
        "accept-language": HeaderBuilder.accept_language,
        "origin": IMAGE_ORIGIN,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site",
    }
    response = requests.post(
        f"https://{node['upload_host']}/upload/v1/{node['store_uri']}",
        headers=headers, data=data, verify=False, proxies=proxies,
    )
    payload = response.json()
    if payload.get("code") not in (2000, "2000"):
        raise RuntimeError(f"评论图片字节上传失败: {payload}")


def _commit(auth, sts, session_key, user_id, service_id, proxies=None):
    query = {
        "Action": "CommitImageUpload",
        "Version": "2018-08-01",
        "ServiceId": service_id,
        "app_id": IMAGE_APP_ID,
        "user_id": str(user_id),
    }
    body = json.dumps({"SessionKey": session_key}, separators=(",", ":")).encode()
    signed = sign_request(
        sts["AccessKeyID"], sts["SecretAccessKey"], sts["SessionToken"],
        method="POST", query_params=query, body=body,
    )
    response = requests.post(
        f"https://{IMAGEX_HOST}/",
        headers=_gateway_headers(signed, content_type="application/json"),
        params=query, data=body, verify=False, proxies=proxies,
    )
    payload = response.json()
    result = payload.get("Result") or {}
    items = result.get("PluginResult") or []
    if not items:
        raise RuntimeError(f"评论图片 CommitImageUpload 失败: {payload}")
    return items[0]


def upload_comment_image(auth, image, *, user_id="", proxies=None):
    data, width, height, image_format = _image_bytes(image)
    user_id = str(user_id or auth.get_uid())
    sts = get_comment_upload_auth(auth, proxies=proxies)
    service_id = sts.pop("service_id")
    node = _apply(auth, sts, user_id, service_id, proxies=proxies)
    _upload_bytes(auth, node, data, user_id, proxies=proxies)
    info = _commit(auth, sts, node["session_key"], user_id, service_id, proxies=proxies)
    return {
        "image_uri_list": info.get("ImageUri") or info.get("Uri") or "",
        "image_widths": int(info.get("ImageWidth") or width),
        "image_heights": int(info.get("ImageHeight") or height),
        "image_formats": info.get("ImageFormat") or image_format,
    }
