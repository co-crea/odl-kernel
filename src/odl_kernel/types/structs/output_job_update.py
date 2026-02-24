# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from typing import Optional
from pydantic import BaseModel, Field

from ..enums import JobStatus

class JobUpdate(BaseModel):
    """
    計算の結果、ジョブ自体（コンテナ）に発生させるべき変更。
    Hostはこれを見て jobs テーブルを更新する。
    
    Use Cases:
        - 鎮火完了: STOPPING -> CANCELLED
        - 全工程完了: RUNNING -> ALL_DONE
        - 致命的エラー: RUNNING -> FAILED
    """
    status: Optional[JobStatus] = None
    # 将来的には global_context の更新などもここに入る可能性がある