# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from .input_intervention_intent import InterventionIntent
from .input_kernel_event_type import KernelEventType

class KernelEvent(BaseModel):
    """
    Analyzeをトリガーする事象。
    「いつ（Time）」「何が（Type）」「どこで（Target）」起きたかを定義する。
    """
    type: KernelEventType
    occurred_at: datetime
    
    # イベントの発生源（TickやGlobal操作の場合はNone）
    target_node_id: Optional[str] = None
    
    # 介入の意図 (MANUAL_INTERVENTIONの場合のみ必須)
    intervention_intent: Optional[InterventionIntent] = None

    # イベント固有データ
    # ACTION_COMPLETED -> { "result": ..., "output": ... }
    # RETRY -> { "target_node_ids": [...] }
    payload: Dict[str, Any] = Field(default_factory=dict)