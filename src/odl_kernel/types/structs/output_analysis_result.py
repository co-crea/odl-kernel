# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from typing import List, Optional
from pydantic import BaseModel, Field

from ..entities import ProcessNode
from .output_job_update import JobUpdate
from .output_runtime_command import RuntimeCommand

class AnalysisResult(BaseModel):
    """
    1回のAnalyzeサイクル（計算）の最終結果。
    Hostはこのオブジェクトを受け取り、「データの保存」と「コマンドの実行」を行う。
    """
    # 1. Hostが実行すべき副作用のリスト（順序重要：A -> B -> C）
    # Hostはこれを先頭から順に実行しなければならない
    commands: List[RuntimeCommand] = Field(default_factory=list)

    # 2. 計算によって状態が変化したノードのリスト
    # HostはこのリストにあるノードをDBにUPSERT（保存）しなければならない
    updated_nodes: List[ProcessNode] = Field(default_factory=list)

    # 3. ジョブ自体の更新指示
    # None でなければ、Hostはジョブの状態を遷移させる
    job_update: Optional[JobUpdate] = None