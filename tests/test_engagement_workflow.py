from unittest.mock import Mock

import pytest

from dy_mcp.workflow import EngagementWorkflow


def search_results(count=1):
    return [
        {
            "aweme_info": {
                "aweme_id": str(7400000000000000000 + index),
                "desc": f"作品 {index}",
                "author": {"uid": str(1000 + index), "nickname": f"作者 {index}"},
            }
        }
        for index in range(count)
    ]


def make_workflow(results=None):
    auth = object()
    session = Mock()
    session.get_auth.return_value = auth
    session.proxy_label = "proxy-one:8080"
    api = Mock()
    api.search_some_general_work.return_value = search_results() if results is None else results
    return EngagementWorkflow(session, api=api), auth, session, api


def test_preview_searches_without_writing():
    workflow, auth, _session, api = make_workflow()

    result = workflow.run("猫", "评论文案", "私信文案")

    assert result["status"] == "preview"
    assert result["count"] == 1
    assert result["works"][0]["author_uid"] == "1000"
    api.search_some_general_work.assert_called_once_with(auth, "猫", 3, "0", "0")
    api.publish_comment.assert_not_called()
    api.create_conversation.assert_not_called()
    api.send_msg.assert_not_called()


def test_execution_requires_explicit_confirmation_before_auth():
    workflow, _auth, session, api = make_workflow()

    with pytest.raises(ValueError, match="confirm=true"):
        workflow.run("猫", "评论文案", "私信文案", dry_run=False)

    session.get_auth.assert_not_called()
    api.search_some_general_work.assert_not_called()


def test_execution_comments_then_messages_each_author():
    workflow, auth, _session, api = make_workflow()
    api.publish_comment.return_value = {"status_code": 0}
    api.create_conversation.return_value = ("conversation-id", 123, "ticket")
    api.send_msg.return_value = True

    result = workflow.run(
        "猫", "评论文案", "私信文案",
        dry_run=False, confirm=True, interval_seconds=0,
    )

    assert result["status"] == "completed"
    assert result["completed_count"] == 1
    api.publish_comment.assert_called_once_with(auth, "7400000000000000000", "评论文案")
    api.create_conversation.assert_called_once_with(auth, 1000)
    api.send_msg.assert_called_once_with(auth, "conversation-id", 123, "ticket", "私信文案")
    assert result["results"][0]["comment_status"] == "published"
    assert result["results"][0]["message_status"] == "sent"


def test_message_failure_stops_remaining_work_and_preserves_comment_status():
    workflow, _auth, _session, api = make_workflow(search_results(2))
    api.publish_comment.return_value = {"status_code": 0}
    api.create_conversation.return_value = ("conversation-id", 123, "ticket")
    api.send_msg.return_value = False

    result = workflow.run(
        "猫", "评论文案", "私信文案",
        dry_run=False, confirm=True, interval_seconds=0,
    )

    assert result["status"] == "partial"
    assert result["stopped_on_error"] is True
    assert len(result["results"]) == 1
    assert result["results"][0]["status"] == "partial"
    assert result["results"][0]["comment_status"] == "published"
    assert result["results"][0]["message_status"] == "failed"
    assert api.publish_comment.call_count == 1


def test_auth_refreshes_mstoken_through_session_proxy():
    from unittest.mock import patch

    from builder.auth import DouyinAuth

    auth = DouyinAuth()
    auth._proxies = {"http": "http://proxy-one:8080", "https": "http://proxy-one:8080"}
    with patch("builder.auth.generate_dynamic_msToken", return_value="token") as generate:
        assert auth.msToken == "token"

    generate.assert_called_once_with(ttwid="", proxies=auth._proxies)


def test_auth_fetches_signing_certificate_through_session_proxy():
    from unittest.mock import patch

    from builder.auth import DouyinAuth

    auth = DouyinAuth()
    auth.private_key = "private-key"
    auth._proxies = {"http": "http://proxy-one:8080", "https": "http://proxy-one:8080"}
    with patch("utils.bd_ticket.fetch_server_cert", return_value=("cert", "sn")) as fetch, \
            patch("utils.bd_ticket.derive_ecdh_key", return_value=b"key"):
        assert auth.ecdh_key() == b"key"

    assert fetch.call_args.kwargs["proxies"] == auth._proxies
