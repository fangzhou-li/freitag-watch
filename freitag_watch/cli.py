from __future__ import annotations

import argparse
import logging

from .config import STATE_PATH
from .notifiers import (
    deliver_bark, deliver_email, prepare_notifications, send_bark_test, send_email_test,
)
from .runner import collect, utc_now
from .sitegen import build_public_site
from .storage import load_state, save_state


def _prepare() -> None:
    state = load_state(STATE_PATH)
    count = prepare_notifications(state, utc_now())
    save_state(STATE_PATH, state)
    print(f"已准备 {count} 个通知投递状态")


def _deliver() -> None:
    state = load_state(STATE_PATH)
    now = utc_now()
    bark = deliver_bark(state, now)
    email = deliver_email(state, now)
    save_state(STATE_PATH, state)
    print(f"Bark 已投递 {bark} 个事件；邮件已投递 {email} 个事件")


def _build() -> None:
    state = load_state(STATE_PATH)
    build_public_site(state)
    print("手机网站已生成至 public/")


def main() -> None:
    parser = argparse.ArgumentParser(prog="freitag-watch", description="FREITAG 官网公开商品监控")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("collect", help="采集并更新状态，不发送通知")
    sub.add_parser("prepare-notify", help="预登记待发送通知（之后应先持久化）")
    sub.add_parser("deliver-notify", help="发送已预登记通知")
    sub.add_parser("build-site", help="生成静态手机网站")
    sub.add_parser("run", help="本地完整运行（云端工作流使用更安全的分阶段命令）")
    sub.add_parser("test-bark", help="发送不写入库存的 Bark 测试通知")
    sub.add_parser("test-email", help="发送不写入库存的测试邮件")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.command == "collect":
        print(collect())
    elif args.command == "prepare-notify":
        _prepare()
    elif args.command == "deliver-notify":
        _deliver()
    elif args.command == "build-site":
        _build()
    elif args.command == "run":
        print(collect())
        _prepare()
        _deliver()
        _build()
    elif args.command == "test-bark":
        send_bark_test()
        print("Bark 测试通知已发送")
    elif args.command == "test-email":
        send_email_test()
        print("测试邮件已发送")


if __name__ == "__main__":
    main()

