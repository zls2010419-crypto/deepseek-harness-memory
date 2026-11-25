"""艾宾浩斯遗忘曲线与间隔复习调度。

遗忘曲线用指数衰减模型近似：

    R(t) = base_retention * exp(-decay_lambda * t)

其中 ``t`` 为距上次复习的天数。重要度高的记忆遗忘更慢（衰减速率打折），
复习按艾宾浩斯经典间隔 [1, 2, 4, 7, 15, 30] 天逐级晋升。
"""
from __future__ import annotations

import math
from typing import Any, List


class ForgettingCurve:
    def __init__(self, cfg):
        self.enabled = cfg.get("forgetting.enabled", True)
        self.intervals: List[int] = [int(x) for x in
                                     cfg.get("forgetting.intervals", [1, 2, 4, 7, 15, 30])]
        self.decay_lambda = float(cfg.get("forgetting.decay_lambda", 0.10))
        self.base_retention = float(cfg.get("forgetting.base_retention", 0.9))

    def retention(self, age_days: float, importance: float = 0.5) -> float:
        """返回时刻 t 的记忆保持率 R(t)，重要度越高衰减越慢。"""
        if not self.enabled:
            return 1.0
        # 重要度打折：0 -> 1.6x 速率，1 -> 0.6x 速率
        lam = self.decay_lambda * (1.6 - importance)
        r = self.base_retention * math.exp(-lam * max(age_days, 0.0))
        return max(0.0, min(1.0, r))

    def next_interval_days(self, box: int) -> int:
        """根据当前复习盒子返回下一次复习间隔（越靠后间隔越长）。"""
        if box < 0:
            box = 0
        if box < len(self.intervals):
            return self.intervals[box]
        return self.intervals[-1]

    def should_review(self, box: int, age_days: float, importance: float = 0.5,
                      threshold: float = 0.65) -> bool:
        """保持率低于阈值即需要复习。"""
        return self.retention(age_days, importance) < threshold
