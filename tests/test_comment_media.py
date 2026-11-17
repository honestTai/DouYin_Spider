import io
from unittest.mock import Mock

from PIL import Image

from dy_apis import douyin_comment_media as media
from dy_mcp.engine import MultiAccountEngine
from dy_mcp.store import AccountStore
from dy_mcp.workflow import EngagementWorkflow


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (64, 64), (45, 110, 220)).save(output, format="PNG")
    return output.getvalue()


def test_upload_comment_image_returns_publish_fields(monkeypatch):
    monkeypatch.setattr(media, "get_comment_upload_auth", lambda *_args, **_kwargs: {
        "AccessKeyID": "access", "SecretAccessKey": "secret", "SessionToken": "token",
        "service_id": "service",
    })
    monkeypatch.setattr(media, "_apply", lambda *_args, **_kwargs: {
        "store_uri": "store", "auth": "auth", "upload_host": "host", "session_key": "session",
    })
    upload = Mock()
    monkeypatch.setattr(media, "_upload_bytes", upload)
    monkeypatch.setattr(media, "_commit", lambda *_args, **_kwargs: {
        "ImageUri": "image-uri", "ImageWidth": 64, "ImageHeight": 64, "ImageFormat": "png",
    })
    auth = Mock()
    auth.get_uid.return_value = "123"

    result = media.upload_comment_image(auth, png_bytes())

    assert result == {
        "image_uri_list": "image-uri", "image_widths": 64,
        "image_heights": 64, "image_formats": "png",
    }
    assert upload.call_count == 1


def test_image_only_workflow_previews_and_executes_upload():
    session = Mock()
    session.get_auth.return_value = object()
    session.proxy_label = "direct"
    api = Mock()
    api.search_some_general_work.return_value = [{
        "aweme_info": {
            "aweme_id": "work", "desc": "作品",
            "author": {"uid": "100", "nickname": "作者"},
        }
    }]
    api.publish_comment.return_value = {
        "status_code": 0,
        "image_upload": {"image_uri_list": "uri", "image_widths": 64,
                         "image_heights": 64, "image_formats": "png"},
    }
    workflow = EngagementWorkflow(session, api=api)

    preview = workflow.run("猫", "", "", image_path="/tmp/image.png")
    published = workflow.run(
        "猫", "", "", image_path="/tmp/image.png", dry_run=False, confirm=True,
    )

    assert preview["planned_actions"] == ["upload_comment_image", "publish_comment"]
    assert api.publish_comment.call_args.kwargs["image_path"] == "/tmp/image.png"
    assert published["results"][0]["image_upload"]["image_uri_list"] == "uri"


def test_multi_account_accepts_image_only_configuration(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    account = store.upsert_account(
        "图片账号", browser_type="webbridge", keywords=["Claude"],
        comment_texts=[], image_paths=["/tmp/image.png"],
    )
    api = Mock()
    api.search_some_general_work.return_value = [{
        "aweme_info": {
            "aweme_id": "work", "desc": "作品",
            "author": {"uid": "100", "nickname": "作者"},
            "statistics": {"digg_count": 5000, "comment_count": 2},
        }
    }]
    store.save_runtime(account["id"], {"DY_COOKIES": "sessionid=test"}, {})
    engine = MultiAccountEngine(
        store,
        runtime_loader=lambda _account: (_ for _ in ()).throw(AssertionError("不应访问浏览器")),
        api=api, auth_factory=lambda *_args, **_kwargs: Mock(),
    )

    result = engine.run(account["id"])

    assert result["status"] == "preview"
    assert result["comment_text"] == ""
    assert result["image_path"] == "/tmp/image.png"
    assert store.get_account(account["id"])["image_paths"] == ["/tmp/image.png"]
