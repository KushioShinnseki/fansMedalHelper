"""
B站粉丝牌助手主程序 - 重构版
"""

import asyncio
import itertools
import os
import signal
import sys
import warnings
import threading
from typing import List

import aiohttp

from src import BiliUser, Config, LogManager


__VERSION__ = "1.0.1"


# 忽略时区警告
warnings.filterwarnings(
    "ignore",
    message="The localize method is no longer necessary, as this time zone supports the fold attribute",
)


# 设置工作目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))


class FansMedalHelper:
    """B站粉丝牌助手主类"""

    def __init__(self):
        self.config = Config()
        self.log = LogManager.get_system_logger()

        LogManager.setup_logger()

        self._shutdown_event = asyncio.Event()
        self._current_users = []

    # =========================================================
    # 信号处理
    # =========================================================

    def _signal_handler(self, signum, frame):
        """信号处理器 - 立即退出"""

        self.log.warning(
            f"接收到信号 {signum}，立即退出..."
        )

        self._shutdown_event.set()

        try:
            loop = asyncio.get_event_loop()

            if loop.is_running():
                loop.create_task(
                    self._immediate_cleanup()
                )
            else:
                asyncio.run(
                    self._immediate_cleanup()
                )

        except Exception as e:
            self.log.error(
                f"清理资源时出错: {e}"
            )

        finally:
            self.log.warning(
                "强制退出程序"
            )

            # 立即退出
            os._exit(0)

    async def _immediate_cleanup(self):
        """立即清理资源"""

        try:

            if not self._current_users:
                return

            cleanup_tasks = []

            for user in self._current_users:

                if (
                    hasattr(user, "session")
                    and user.session
                    and not user.session.closed
                ):
                    cleanup_tasks.append(
                        user.session.close()
                    )

            if cleanup_tasks:

                await asyncio.wait_for(
                    asyncio.gather(
                        *cleanup_tasks,
                        return_exceptions=True,
                    ),
                    timeout=2.0,
                )

        except asyncio.TimeoutError:

            self.log.warning(
                "清理超时，强制退出"
            )

        except Exception as e:

            self.log.error(
                f"立即清理失败: {e}"
            )

    def setup_signal_handlers(self):
        """设置信号处理器"""

        # Python 的 signal.signal()
        # 只能在主线程调用
        if (
            threading.current_thread()
            is not threading.main_thread()
        ):
            return

        try:

            signal.signal(
                signal.SIGINT,
                self._signal_handler,
            )

            signal.signal(
                signal.SIGTERM,
                self._signal_handler,
            )

        except Exception as e:

            self.log.warning(
                f"设置信号处理器失败: {e}"
            )

    # =========================================================
    # 用户资源
    # =========================================================

    async def cleanup_users(self):
        """清理所有用户资源"""

        if not self._current_users:
            return

        self.log.info(
            "正在清理用户资源..."
        )

        cleanup_tasks = []

        for user in self._current_users:

            if (
                hasattr(user, "session")
                and user.session
                and not user.session.closed
            ):
                cleanup_tasks.append(
                    user.session.close()
                )

        if cleanup_tasks:

            try:

                await asyncio.gather(
                    *cleanup_tasks,
                    return_exceptions=True,
                )

                self.log.success(
                    "用户资源清理完成"
                )

            except Exception as e:

                self.log.error(
                    f"清理用户资源时出错: {e}"
                )

        self._current_users.clear()

    async def initialize_users(
        self,
        users_config: List[dict],
    ) -> List[BiliUser]:
        """初始化用户列表"""

        users = []
        init_tasks = []

        for user_config in users_config:

            if not user_config.get(
                "access_key"
            ):
                continue

            bili_user = BiliUser(
                user_config["access_key"],
                user_config.get(
                    "white_uid",
                    "",
                ),
                user_config.get(
                    "banned_uid",
                    "",
                ),
                self.config.config,
            )

            users.append(
                bili_user
            )

            init_tasks.append(
                bili_user.init()
            )

        # 保存用户列表
        # 方便程序退出时清理资源
        self._current_users = users

        if init_tasks:

            try:

                await asyncio.gather(
                    *init_tasks
                )

            except Exception as e:

                self.log.error(
                    f"用户初始化失败: {e}"
                )

                await self.cleanup_users()

                raise

        return users

    # =========================================================
    # 任务执行
    # =========================================================

    async def execute_tasks(
        self,
        users: List[BiliUser],
    ) -> List[str]:
        """执行所有用户的任务"""

        message_list = []

        try:

            # 检查退出信号
            if self._shutdown_event.is_set():

                self.log.warning(
                    "检测到退出信号，取消任务执行"
                )

                return [
                    "任务被用户中断"
                ]

            # 并发执行所有用户任务
            start_tasks = [
                user.start()
                for user in users
            ]

            await asyncio.gather(
                *start_tasks,
                return_exceptions=True,
            )

        except KeyboardInterrupt:

            self.log.warning(
                "检测到键盘中断 (Ctrl+C)"
            )

            message_list.append(
                "任务被用户中断"
            )

        except Exception as e:

            self.log.exception(
                f"任务执行异常: {e}"
            )

            message_list.append(
                f"任务执行失败: {e}"
            )

        finally:

            # 收到退出信号
            if self._shutdown_event.is_set():

                self.log.info(
                    "收到退出信号，跳过消息收集"
                )

                return (
                    message_list
                    or ["任务被中断"]
                )

            try:

                # 收集用户消息
                msg_tasks = [
                    user.send_msg()
                    for user in users
                ]

                user_messages = await asyncio.gather(
                    *msg_tasks,
                    return_exceptions=True,
                )

                # 过滤异常
                valid_messages = [
                    msg
                    for msg in user_messages
                    if not isinstance(
                        msg,
                        Exception,
                    )
                ]

                message_list.extend(
                    list(
                        itertools.chain.from_iterable(
                            valid_messages
                        )
                    )
                )

            except Exception as e:

                self.log.error(
                    f"消息收集失败: {e}"
                )

                message_list.append(
                    f"消息收集失败: {e}"
                )

        return message_list

    # =========================================================
    # 推送
    # =========================================================

    async def push_notifications(
        self,
        session: aiohttp.ClientSession,
        messages: List[str],
    ):
        """推送通知"""

        try:

            notification_config = (
                self.config.get_notification_config()
            )

            # Server酱
            if notification_config.get(
                "SENDKEY"
            ):

                await self._push_to_server_chan(
                    session,
                    notification_config[
                        "SENDKEY"
                    ],
                    messages,
                )

            # 其他平台
            if notification_config.get(
                "MOREPUSH"
            ):

                await self._push_to_more_platforms(
                    messages,
                    notification_config[
                        "MOREPUSH"
                    ],
                )

        except Exception as e:

            self.log.error(
                f"推送通知失败: {e}"
            )

    async def _push_to_server_chan(
        self,
        session: aiohttp.ClientSession,
        sendkey: str,
        messages: List[str],
    ):
        """推送到Server酱"""

        content = "  \n".join(
            messages
        )

        data = {
            "text": "【B站粉丝牌助手推送】",
            "desp": content,
        }

        try:

            async with session.post(
                f"https://sctapi.ftqq.com/{sendkey}.send",
                data=data,
            ) as resp:

                if resp.status == 200:

                    self.log.success(
                        "Server酱推送成功"
                    )

                else:

                    self.log.error(
                        f"Server酱推送失败: {resp.status}"
                    )

        except Exception as e:

            self.log.error(
                f"Server酱推送异常: {e}"
            )

    async def _push_to_more_platforms(
        self,
        messages: List[str],
        morepush_config: dict,
    ):
        """推送到更多平台"""

        try:

            from onepush import notify

            notifier = morepush_config[
                "notifier"
            ]

            params = morepush_config[
                "params"
            ]

            notify(
                notifier,
                title="【B站粉丝牌助手推送】",
                content="  \n".join(
                    messages
                ),
                **params,
                proxy=self.config.get(
                    "PROXY"
                ),
            )

            self.log.success(
                f"{notifier} 推送成功"
            )

        except ImportError:

            self.log.warning(
                "onepush 库未安装，跳过推送"
            )

        except Exception as e:

            self.log.error(
                f"推送异常: {e}"
            )

    # =========================================================
    # 单次任务
    # =========================================================

    async def run(self):
        """运行一次主程序"""

        self.log.warning(
            f"当前版本为: {__VERSION__}"
        )

        session = aiohttp.ClientSession(
            trust_env=True
        )

        try:

            # 设置 Linux / Windows 信号
            self.setup_signal_handlers()

            # 初始化用户
            users = await self.initialize_users(
                self.config.get_users()
            )

            if not users:

                self.log.warning(
                    "没有有效的用户配置"
                )

                return

            # 检查退出信号
            if self._shutdown_event.is_set():

                self.log.warning(
                    "程序启动期间收到退出信号"
                )

                return

            # 执行任务
            messages = await self.execute_tasks(
                users
            )

            # 输出消息
            for message in messages:

                self.log.info(
                    message
                )

            # 推送通知
            if not self._shutdown_event.is_set():

                await self.push_notifications(
                    session,
                    messages,
                )

            else:

                self.log.info(
                    "由于程序被中断，跳过推送通知"
                )

        except KeyboardInterrupt:

            self.log.warning(
                "程序被用户中断 (Ctrl+C)"
            )

        except SystemExit:

            self.log.info(
                "程序正常退出"
            )

        except Exception as e:

            self.log.exception(
                f"程序运行异常: {e}"
            )

        finally:

            try:

                await self.cleanup_users()

                await session.close()

                self.log.info(
                    "程序资源清理完成"
                )

            except Exception as e:

                self.log.error(
                    f"资源清理时出错: {e}"
                )

            self.log.info(
                "程序退出"
            )


# =============================================================
# 主函数
# =============================================================

async def main():
    """主函数"""

    helper = FansMedalHelper()

    await helper.run()


# =============================================================
# 定时器
# =============================================================

def run_with_scheduler():
    """使用定时器运行"""

    try:

        config = Config()

        notification_config = (
            config.get_notification_config()
        )

        cron = notification_config.get(
            "CRON"
        )

        log = LogManager.get_system_logger()

        # -----------------------------------------------------
        # CRON 定时模式
        # -----------------------------------------------------

        if cron:

            from apscheduler.schedulers.blocking import (
                BlockingScheduler
            )

            from apscheduler.triggers.cron import (
                CronTrigger
            )

            timezone = "Asia/Shanghai"

            log.info(
                f"使用内置定时器 {cron}，"
                f"时区: {timezone}"
            )

            scheduler = BlockingScheduler(
                timezone=timezone
            )

            scheduler.add_job(
                lambda: asyncio.run(
                    main()
                ),
                CronTrigger.from_crontab(
                    cron,
                    timezone=timezone,
                ),
                id="fans_medal_daily_task",
                replace_existing=True,
                misfire_grace_time=3600,
                coalesce=True,
                max_instances=1,
            )

            log.info(
                "定时任务已启动，等待下一次执行..."
            )

            try:

                scheduler.start()

            except KeyboardInterrupt:

                log.warning(
                    "定时任务被用户中断"
                )

                scheduler.shutdown(
                    wait=True
                )

        # -----------------------------------------------------
        # --auto 模式
        # -----------------------------------------------------

        elif "--auto" in sys.argv:

            import datetime

            from apscheduler.schedulers.blocking import (
                BlockingScheduler
            )

            from apscheduler.triggers.interval import (
                IntervalTrigger
            )

            timezone = "Asia/Shanghai"

            log.info(
                "使用自动守护模式，"
                "每隔 24 小时运行一次"
            )

            scheduler = BlockingScheduler(
                timezone=timezone
            )

            scheduler.add_job(
                lambda: asyncio.run(
                    main()
                ),
                IntervalTrigger(
                    hours=24,
                    timezone=timezone,
                ),
                next_run_time=datetime.datetime.now(),
                misfire_grace_time=3600,
                max_instances=1,
            )

            try:

                scheduler.start()

            except KeyboardInterrupt:

                log.warning(
                    "守护任务被用户中断"
                )

                scheduler.shutdown(
                    wait=True
                )

        # -----------------------------------------------------
        # 单次模式
        # -----------------------------------------------------

        else:

            log.info(
                "未配置定时器，开启单次任务"
            )

            try:

                asyncio.run(
                    main()
                )

            except KeyboardInterrupt:

                log.warning(
                    "单次任务被用户中断"
                )

            except Exception as e:

                log.error(
                    f"任务执行异常: {e}"
                )

                raise

            log.info(
                "任务结束"
            )

    except KeyboardInterrupt:

        log.warning(
            "程序被用户中断"
        )

        sys.exit(0)

    except SystemExit:

        log.warning(
            "程序正常退出"
        )

    except Exception as e:

        log.error(
            f"程序启动失败: {e}"
        )

        sys.exit(1)


# =============================================================
# 兼容旧版本
# =============================================================

def run(*args, **kwargs):
    """兼容旧版本的run函数"""

    run_with_scheduler()


# =============================================================
# 程序入口
# =============================================================

if __name__ == "__main__":

    run_with_scheduler()