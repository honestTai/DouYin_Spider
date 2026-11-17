import os
import time

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

    @staticmethod
    def _is_authentication_error(message):
        return any(text in message.lower() for text in (
            "尚未保存登录凭证", "cookie 失效", "cookie失效", "登录已失效", "需要重新登录",
        ))

    def _remaining_quota(self, account):
        settings = self.store.settings()
        global_hour = int(settings.get("global_per_hour", "20"))
        return max(0, min(
            global_hour - self.store.count_published(hours=1),
            account["per_hour_limit"] - self.store.count_published(account["id"], hours=1),
            account["per_day_limit"] - self.store.count_published(account["id"], hours=24),
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
        auth = None
        try:
            saved_runtime = self.store.get_runtime(account_id)
            if not saved_runtime:
                raise RuntimeError("尚未保存登录凭证，请先调用 refresh_account_runtime 绑定浏览器")
            runtime_env = dict(saved_runtime["env"])
            runtime_info = {
                **saved_runtime["info"],
                "credential_source": "saved",
                "runtime_saved_at": saved_runtime["saved_at"],
            }
            if account.get("proxy_url"):
                runtime_env["DY_PROXY_URL"] = account["proxy_url"]
                runtime_info["proxy"] = "已配置独立代理"
            else:
                runtime_env.pop("DY_PROXY_URL", None)
                runtime_info["proxy"] = "环境默认网络"
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
            searched_keywords = []
            actual_strategy = account.get("content_strategy") or "engagement"
            actual_publish_time = "1" if actual_strategy == "latest" else "0"
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
                latest = actual_strategy == "latest"
                hashtag = actual_strategy == "hashtag"
                if latest:
                    strategy_options = [("latest", "2", "1"), ("engagement", "1", "0")]
                elif hashtag:
                    strategy_options = [("hashtag", "0", "0")]
                else:
                    strategy_options = [("engagement", "1", "0")]
                start = previous_runs % len(account["keywords"])
                keywords = account["keywords"][start:] + account["keywords"][:start]
                candidates = []
                for search_keyword in keywords:
                    for strategy, sort_type, publish_time in strategy_options:
                        searched_keywords.append({"keyword": search_keyword, "strategy": strategy})
                        query = f"#{search_keyword.lstrip('#')}" if strategy == "hashtag" else search_keyword
                        works = self.api.search_some_general_work(
                            auth, query, account["candidate_pool_size"],
                            sort_type, publish_time,
                        )
                        candidates = [candidate_from_search(item) for item in works]
                        candidates = [item for item in candidates if item]
                        candidates = [
                            item for item in candidates
                            if (strategy == "hashtag" or (
                                item["digg_count"] >= account["min_digg_count"]
                                and item["comment_count"] <= account["max_comment_count"]
                            ))
                            and not self.store.work_status(item["aweme_id"], account_id)
                        ]
                        if strategy == "hashtag":
                            candidates = candidates[:account["candidate_pool_size"]]
                        elif strategy == "engagement":
                            candidates.sort(
                                key=lambda item: (item["score"], item["digg_count"]), reverse=True,
                            )
                        if candidates:
                            keyword = search_keyword
                            actual_strategy = strategy
                            actual_publish_time = publish_time
                            break
                    if candidates:
                        break
                self.store.update_run_keyword(run_id, keyword)

            planned_count = min(account["batch_size"], self._remaining_quota(account))
            base = {
                "account_id": account_id,
                "account_name": account["name"],
                "profile": runtime_info,
                "run_id": run_id,
                "keyword": keyword,
                "comment_text": comment_text,
                "image_path": image_path,
                "content_strategy": actual_strategy,
                "publish_time": actual_publish_time,
                "searched_keywords": searched_keywords,
                "candidate_count": len(candidates),
                "batch_size": planned_count,
                "batch_interval_seconds": account["batch_interval_seconds"],
                "dry_run": dry_run,
            }
            planned_ids = [item["aweme_id"] for item in candidates[:planned_count]]
            if dry_run:
                self.store.finish_run(
                    run_id, "preview", candidate_count=len(candidates),
                    selected_id=planned_ids[0] if planned_ids else "", selected_ids=planned_ids,
                )
                return {
                    **base,
                    "status": "preview" if planned_count else "rate_limited",
                    "planned_count": planned_count,
                    "works": candidates[:10],
                    "message": "仅预览，未上传图片或发布评论",
                }
            if not candidates:
                self.store.finish_run(run_id, "no_candidates")
                return {**base, "status": "no_candidates", "message": "没有符合筛选条件的新作品"}
            if planned_count <= 0:
                self.store.finish_run(run_id, "rate_limited", candidate_count=len(candidates))
                return {**base, "status": "rate_limited", "message": "已达到当前小时或每日评论限额"}

            results = []
            stopped_error = ""
            for index, candidate in enumerate(candidates[:planned_count]):
                if not self.store.reserve_work(
                    candidate["aweme_id"], account_id, run_id,
                    candidate["digg_count"], candidate["comment_count"],
                ):
                    continue
                try:
                    image_options = {"image_path": image_path} if image_path else {}
                    response = self.api.publish_comment(
                        auth, candidate["aweme_id"], comment_text, **image_options,
                    )
                    if response.get("status_code") not in (0, "0"):
                        raise RuntimeError(
                            f"评论接口返回 status_code={response.get('status_code')}: "
                            f"{response.get('status_msg') or response.get('message') or '未知错误'}"
                        )
                    self.store.publish_work(candidate["aweme_id"], account_id)
                    results.append({
                        **candidate,
                        "status": "completed",
                        "comment_status": "published",
                        "image_upload": response.get("image_upload"),
                    })
                except Exception as error:
                    stopped_error = str(error)
                    self.store.release_work(candidate["aweme_id"], account_id)
                    results.append({
                        **candidate,
                        "status": "failed",
                        "comment_status": "failed",
                        "error": stopped_error,
                    })
                    break
                if (account["batch_interval_seconds"] and index < planned_count - 1):
                    time.sleep(account["batch_interval_seconds"])

            published = [item for item in results if item["status"] == "completed"]
            failed = [item for item in results if item["status"] == "failed"]
            selected_ids = [item["aweme_id"] for item in published]
            if failed:
                status = "partial" if published else "failed"
            elif published:
                status = "completed"
            else:
                status = "no_candidates"
            self.store.finish_run(
                run_id, status, candidate_count=len(candidates),
                selected_id=selected_ids[0] if selected_ids else "",
                selected_ids=selected_ids, error=stopped_error or None,
            )
            account_status = "active"
            if stopped_error and self._is_verification_error(stopped_error):
                account_status = "verification_required"
            elif stopped_error and self._is_authentication_error(stopped_error):
                account_status = "authentication_required"
            self.store.set_account_status(account_id, account_status, stopped_error or None)
            return {
                **base,
                "status": status,
                "comment_status": "published" if published and not failed else status,
                "account_status": account_status,
                "completed_count": len(published),
                "failed_count": len(failed),
                "works": results,
                "work": published[0] if published else None,
                "image_upload": next(
                    (item["image_upload"] for item in published if item.get("image_upload")), None,
                ),
                "error": stopped_error or None,
            }
        except Exception as error:
            message = str(error)
            self.store.finish_run(run_id, "failed", error=message)
            if self._is_verification_error(message):
                status = "verification_required"
            elif self._is_authentication_error(message):
                status = "authentication_required"
            else:
                status = "active"
            self.store.set_account_status(account_id, status, message)
            return {
                "account_id": account_id,
                "run_id": run_id,
                "keyword": keyword,
                "comment_text": comment_text,
                "image_path": image_path,
                "dry_run": dry_run,
                "status": "failed",
                "comment_status": "failed",
                "account_status": status,
                "completed_count": 0,
                "failed_count": 1,
                "error": message,
            }
        finally:
            if auth is not None:
                auth.close()
