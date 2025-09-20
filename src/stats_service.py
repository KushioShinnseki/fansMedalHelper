"""
统计和报告服务模块
"""
from typing import List, Dict, Any, Optional

from .services import BaseService
from .utils import safe_get


class StatsService(BaseService):
    """统计服务"""

    def __init__(self, api, user_name: str, logger=None):
        super().__init__(api, logger)
        self.user_name = user_name

    def calculate_medal_stats(self, medals: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """计算勋章统计"""
        stats = {
            'full': [],      # 30
            'high': [],      # 1200-30
            'medium': [],    # 300-1200
            'low': [],       # <300
            'unlit': []      # 未点亮
        }

        for medal in medals:
            today_feed = safe_get(medal, 'medal', 'today_feed', default=0)
            level = safe_get(medal, 'medal', 'level', default=0)
            nick_name = safe_get(medal, 'anchor_info',
                                 'nick_name', default='未知用户')
            is_lighted = safe_get(medal, 'medal', 'is_lighted', default=1)

            if not is_lighted:
                stats['unlit'].append(nick_name)

            if today_feed >= 30:
                stats['full'].append(nick_name)
            elif 1200 <= today_feed < 30:
                stats['high'].append(nick_name)
            elif 300 <= today_feed < 1200:
                stats['medium'].append(nick_name)
            elif today_feed < 300:
                stats['low'].append(nick_name)

        return stats

    def generate_report_messages(self, stats: Dict[str, List[str]]) -> List[str]:
        """生成统计报告消息"""
        messages = [f"【{self.user_name}】 今日亲密度获取情况如下："]

        labels = {
            'full': '【30】',
            'high': '【1200至30】',
            'medium': '【300至1200】',
            'low': '【300以下】',
            'unlit': '【未点亮】'
        }

        for key, label in labels.items():
            name_list = stats[key]
            if name_list:
                display_names = ' '.join(name_list[:5])
                if len(name_list) > 5:
                    display_names += '等'
                messages.append(f"{label}{display_names} {len(name_list)}个")

        return messages

    async def get_current_medal_info(self, initial_medal: Dict[str, Any]) -> List[str]:
        """获取当前佩戴勋章信息"""
        messages = []

        try:
            initial_medal_info = await self.api.getMedalsInfoByUid(initial_medal['target_id'])

            if initial_medal_info.get('has_fans_medal'):
                medal = initial_medal_info['my_fans_medal']
                messages.append(
                    f"【当前佩戴】「{medal['medal_name']}」({medal['target_name']}) "
                    f"{medal['level']} 级 "
                )

                if medal['today_feed'] != 0:
                    messages.extend([
                        f"今日已获取亲密度 {medal['today_feed']} (B站结算有延迟，请耐心等待)",
                    ])
        except Exception as e:
            self.log.error(f"获取当前勋章信息失败: {e}")

        return messages

    async def execute(self, medals: List[Dict[str, Any]], initial_medal: Optional[Dict[str, Any]] = None) -> List[str]:
        """生成完整的统计报告"""
        stats = self.calculate_medal_stats(medals)
        messages = self.generate_report_messages(stats)

        if initial_medal:
            medal_info = await self.get_current_medal_info(initial_medal)
            messages.extend(medal_info)

        return messages
