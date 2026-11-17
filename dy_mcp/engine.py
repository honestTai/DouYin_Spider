import os

from .browser_runtime import collect_runtime_for_account
from .store import AccountStore


def as_count(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def candidate_from_search(item):
    work = item.get("aweme_info") or {}
    author = work.get("author") or {}
    stats = work.get("statistics") or {}
    aweme_id = str(work.get("aweme_id") or "")
    if not aweme_id:
        return None
    digg = as_count(stats.get("digg_count") or work.get("digg_count"))
    comments = as_count(stats.get("comment_count") or work.get("comment_count"))
    return {
        "aweme_id": aweme_id,
        "work_url": f"https://www.douyin.com/video/{aweme_id}",
        "title": work.get("desc") or "",
        "author_uid": str(author.get("uid") or author.get("user_id") or ""),
        "author_nickname": author.get("nickname") or "",
        "digg_count": digg,
        "comment_count": comments,
        "score": round(digg / (comments + 1), 2),
    }


class MultiAccountEngine:
    def __init__(self, store=None, runtime_loader=collect_runtime_for_account,
                 api=None, auth_factory=None):
        self.store = store or AccountStore()
        self.runtime_loader = runtime_loader
        self.api = api
        self.auth_factory = auth_factory

    @staticmethod
    def _is_verification_error(message):
        return any(text in message for text in (
            "二次身份验证", "scene=comment", "ticket/ts_sign", "同会话", "dtrait",
        ))

    def run(self, account_id, *, dry_run=True, confirm=False, aweme_id=""):
        account = self.store.get_account(account_id)
        if not account:
            raise ValueError("账号不存在")
        if not account["enabled"]:
            raise ValueError("账号已停用")
        if not dry_run and not confirm:
            raise ValueError("真实评论必须同时设置 dry_run=false 和 confirm=true")
        previous_runs = len(self.store.recent_runs(limit=1000, account_id=account_id))
        keyword = account["keywords"][previous_runs % len(account["keywords"])]
        comment_text = (account["comment_texts"][previous_runs % len(account["comment_texts"])]
                        if account["comment_texts"] else "")
        image_path = (account["image_paths"][previous_runs % len(account["image_paths"])]
                      if account["image_paths"] else "")
        run_id = self.store.create_run(account_id, keyword, comment_text, dry_run)
        reserved_id = ""
        auth = None
        try:
            runtime_env, runtime_info = self.runtime_loader(account)
            os.environ.update(runtime_env)
            if self.api is None or self.auth_factory is None:
                from dy_apis.douyin_api import DouyinAPI
                from builder.auth import DouyinAuth
                self.api = DouyinAPI
                self.auth_factory = DouyinAuth.from_cookie

            from .proxy_pool import ProxyPool
            proxies = ProxyPool.request_config(runtime_env.get("DY_PROXY_URL") or None)
            auth = self.auth_factory(
                runtime_env["DY_COOKIES"], bootstrap_creator=False, proxies=proxies,
            )
            if aweme_id and self.store.work_status(aweme_id, account_id):
                candidates = []
            elif aweme_id:
                candidates = [{
                    "aweme_id": aweme_id,
                    "work_url": f"https://www.douyin.com/video/{aweme_id}",
                    "title": "定向指定作品",
                    "author_uid": "",
                    "author_nickname": "",
                    "digg_count": 0,
                    "comment_count": 0,
                    "score": 0,
                }]
            else:
                works = self.api.search_some_general_work(
                    auth, keyword, account["candidate_pool_size"], "1", "0",
                )
                candidates = [candidate_from_search(item) for item in works]
                candidates = [item for item in candidates if item]
                candidates = [
                    item for item in candidates
                    if item["digg_count"] >= account["min_digg_count"]
                    and item["comment_count"] <= account["max_comment_count"]
                    and not self.store.work_status(item["aweme_id"], account_id)
                ]
                candidates.sort(
                    key=lambda item: (item["score"], item["digg_count"]), reverse=True,
                )
            base = {
                "account_id": account_id,
                "account_name": account["name"],
                "profile": runtime_info,
                "run_id": run_id,
                "keyword": keyword,
                "comment_text": comment_text,
                "image_path": image_path,
                "candidate_count": len(candidates),
                "dry_run": dry_run,
            }
            if dry_run:
                self.store.finish_run(
                    run_id, "preview", candidate_count=len(candidates),
                    selected_id=candidates[0]["aweme_id"] if candidates else "",
                )
                return {
                    **base,
                    "status": "preview",
                    "works": candidates[:10],
                    "message": "仅预览，未上传图片或发布评论",
                }
            if not candidates:
                self.store.finish_run(run_id, "no_candidates")
                return {**base, "status": "no_candidates", "message": "没有符合筛选条件的新作品"}

            selected = None
            for candidate in candidates:
                if self.store.reserve_work(
                    candidate["aweme_id"], account_id, run_id,
                    candidate["digg_count"], candidate["comment_count"],
                ):
                    selected = candidate
                    reserved_id = candidate["aweme_id"]
                    break
            if selected is None:
                self.store.finish_run(run_id, "no_candidates", candidate_count=len(candidates))
                return {**base, "status": "no_candidates", "message": "候选作品已被其他任务占用"}

            image_options = {"image_path": image_path} if image_path else {}
            response = self.api.publish_comment(
                auth, selected["aweme_id"], comment_text, **image_options,
            )
            if response.get("status_code") not in (0, "0"):
                raise RuntimeError(
                    f"评论接口返回 status_code={response.get('status_code')}: "
                    f"{response.get('status_msg') or response.get('message') or '未知错误'}"
                )
            self.store.publish_work(reserved_id, account_id)
            self.store.finish_run(
                run_id, "completed", candidate_count=len(candidates), selected_id=reserved_id,
            )
            self.store.set_account_status(account_id, "active")
            return {
                **base,
                "status": "completed",
                "comment_status": "published",
                "image_upload": response.get("image_upload"),
                "work": selected,
            }
        except Exception as error:
            message = str(error)
            if reserved_id:
                self.store.release_work(reserved_id, account_id)
            self.store.finish_run(run_id, "failed", selected_id=reserved_id, error=message)
            status = "verification_required" if self._is_verification_error(message) else "active"
            self.store.set_account_status(account_id, status, message)
            return {
                "account_id": account_id,
                "run_id": run_id,
                "keyword": keyword,
                "comment_text": comment_text,
                "dry_run": dry_run,
                "status": "failed",
                "comment_status": "failed",
                "account_status": status,
                "error": message,
            }
        finally:
            if auth is not None:
                auth.close()
