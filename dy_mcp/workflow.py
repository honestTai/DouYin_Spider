import threading
import time

from dy_apis.douyin_api import DouyinAPI


class EngagementWorkflow:
    def __init__(self, session, api=DouyinAPI):
        self.session = session
        self.api = api
        self._lock = threading.Lock()

    def run(self, query, comment_text, message_text, *, image_path="", limit=3, dry_run=True,
            confirm=False, sort_type="0", publish_time="0", interval_seconds=3.0):
        query = str(query or "").strip()
        comment_text = str(comment_text or "").strip()
        message_text = str(message_text or "").strip()
        image_path = str(image_path or "").strip()
        if not query:
            raise ValueError("query 不能为空")
        if not comment_text and not image_path:
            raise ValueError("comment_text 和 image_path 不能同时为空")
        if not 1 <= limit <= 20:
            raise ValueError("limit 必须在 1 到 20 之间")
        if sort_type not in {"0", "1", "2"}:
            raise ValueError("sort_type 只支持 0、1、2")
        if publish_time not in {"0", "1", "7", "180"}:
            raise ValueError("publish_time 只支持 0、1、7、180")
        if not 0 <= interval_seconds <= 60:
            raise ValueError("interval_seconds 必须在 0 到 60 之间")
        if not dry_run and not confirm:
            raise ValueError("真实执行必须同时设置 dry_run=false 和 confirm=true")

        with self._lock:
            auth = self.session.get_auth()
            works = self.api.search_some_general_work(
                auth, query, limit, sort_type, publish_time,
            )
            candidates = [self._candidate(item) for item in works if item.get("aweme_info")]
            base = {
                "query": query,
                "count": len(candidates),
                "proxy": getattr(self.session, "proxy_label", "unknown"),
                "comment_text": comment_text,
                "message_text": message_text,
                "image_path": image_path,
            }
            if dry_run:
                planned_actions = ["publish_comment"]
                if image_path:
                    planned_actions.insert(0, "upload_comment_image")
                if message_text:
                    planned_actions.append("private_message_author")
                return {
                    **base,
                    "status": "preview",
                    "works": candidates,
                    "planned_actions": planned_actions,
                    "message": "仅预览，未发布评论或私信",
                }
            return self._execute(auth, candidates, base, interval_seconds)

    def _execute(self, auth, candidates, base, interval_seconds):
        results = []
        stopped = False
        for index, candidate in enumerate(candidates):
            result = {
                **candidate,
                "comment_status": "pending",
                "message_status": "pending" if base["message_text"] else "skipped",
            }
            try:
                image_options = {"image_path": base["image_path"]} if base["image_path"] else {}
                response = self.api.publish_comment(
                    auth, candidate["aweme_id"], base["comment_text"], **image_options,
                )
                if response.get("image_upload"):
                    result["image_upload"] = response["image_upload"]
                if response.get("status_code") not in (0, "0"):
                    raise RuntimeError(
                        f"评论接口返回 status_code={response.get('status_code')}: "
                        f"{response.get('status_msg') or response.get('message') or '未知错误'}"
                    )
                result["comment_status"] = "published"
                if base["message_text"]:
                    conversation = self.api.create_conversation(auth, int(candidate["author_uid"]))
                    if not self.api.send_msg(auth, *conversation, base["message_text"]):
                        raise RuntimeError("私信接口未返回成功")
                    result["message_status"] = "sent"
                result["status"] = "completed"
            except Exception as error:
                result["status"] = "partial" if result["comment_status"] == "published" else "failed"
                if result["comment_status"] == "pending":
                    result["comment_status"] = "failed"
                if result["message_status"] == "pending" and result["comment_status"] == "published":
                    result["message_status"] = "failed"
                result["error"] = str(error)
                stopped = True
            results.append(result)
            if stopped:
                break
            if interval_seconds and index < len(candidates) - 1:
                time.sleep(interval_seconds)

        completed = sum(item["status"] == "completed" for item in results)
        if stopped:
            has_writes = any(item["comment_status"] == "published" for item in results)
            status = "partial" if has_writes else "failed"
        else:
            status = "completed"
        return {
            **base,
            "status": status,
            "executed": True,
            "completed_count": completed,
            "stopped_on_error": stopped,
            "results": results,
        }

    @staticmethod
    def _candidate(item):
        work = item["aweme_info"]
        author = work.get("author") or {}
        aweme_id = str(work.get("aweme_id") or "")
        author_uid = author.get("uid") or author.get("user_id") or ""
        if not aweme_id or not author_uid:
            raise ValueError("搜索结果缺少作品 ID 或作者 UID")
        return {
            "aweme_id": aweme_id,
            "work_url": f"https://www.douyin.com/video/{aweme_id}",
            "title": work.get("desc") or "",
            "author_uid": str(author_uid),
            "author_nickname": author.get("nickname") or "",
        }
