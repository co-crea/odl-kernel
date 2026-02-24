# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from typing import Any, Dict, List

from odl_kernel.types import ProcessNode, LifecycleStatus, OpCode
from .base import ExpansionStrategy, ExpansionPlan

class SerialExpansionStrategy(ExpansionStrategy):
    """
    Serial Expansion Logic (Strict Path Resolution)
    
    Architecture:
        L3 Mechanism (Logic) - Pure Domain Logic
    
    Responsibility:
        定義された子ノード群（Blueprint）を、先頭から順に「一つずつ」展開計画に追加する (Lazy Expansion)。
        直前の子ノードが完了 (COMPLETED) するまで、次のノードの生成をブロックすることで、
        厳密な順序実行 (Sequential Execution) を強制する。
        
        [Data Injection]
        `fan_out` 展開における「兄(iterator_init)から弟(iterate)へのデータ受け渡し」を担う。
        兄が取得した外部リストデータを、弟の `params["items"]` に動的に注入することで、
        Iterate展開のデータソースを提供する。
    
    Path Resolution (Strict Inheritance):
        Blueprintの `stack_path` は未解決トークンを含む可能性があるため、信頼せず使用しない。
        必ず「親の解決済みパス (`parent.stack_path`)」と「自身のノード名」を結合し、
        親の実行コンテキストを継承した物理パスを生成する。
        
    Context & Data:
        本Strategyはコンテキスト変数 ($PREV等) の注入を行わない。
        データの依存関係は、各ノードの Wiring 定義によって明示的に解決される (Explicit Over Implicit)。
    """

    def plan_next_nodes(
        self,
        parent: ProcessNode,
        current_children: List[ProcessNode]
    ) -> List[ExpansionPlan]:
        """
        Args:
            parent: 親ノード（Blueprints, Resolved Path保持）
            current_children: 既に生成されている子ノードのリスト（生成順にソート済みであることが前提）

        Returns:
            List[ExpansionPlan]: 次に生成すべき単一のノード計画、または空リスト（待機/完了）。
        """
        blueprints = parent.children_blueprint
        total_blueprints = len(blueprints)
        current_count = len(current_children)

        # 1. Completion Check
        if current_count >= total_blueprints:
            return []

        # 2. Sequential Wait
        if current_count > 0:
            last_child = current_children[-1]

            # 兄が終わっていなければ、弟はまだ産まない（待機）
            if last_child.lifecycle_status != LifecycleStatus.COMPLETED:
                return []

        # 3. Target Identification
        next_blueprint = blueprints[current_count]

        # 4. Path Resolution (Strict)
        node_name = self._get_node_name(next_blueprint)
        resolved_path = f"{parent.stack_path}/{node_name}"

        # 5. Parameter Injection (For Fan-out) [NEW]
        params_override: Dict[str, Any] = {}

        # 次に産むのが ITERATE で、かつ兄が存在する場合
        if next_blueprint.opcode == OpCode.ITERATE and current_count > 0:
            prev_child = current_children[-1]
            
            # 兄が ITERATOR_INIT であるか確認
            if prev_child.opcode == OpCode.ITERATOR_INIT:
                # 兄が成果物（解決されたデータリスト）を持っているか確認
                if prev_child.runtime_context.output_aggregation:
                    # 最新の成果物を取得
                    items_data = prev_child.runtime_context.output_aggregation[-1]
                    
                    # 弟の params["items"] に注入する指示を作成
                    params_override["items"] = items_data

        # 6. Create Plan
        return [ExpansionPlan(
            blueprint=next_blueprint,
            context_vars={}, # Context注入なし
            resolved_path=resolved_path,
            original_index=current_count,
            params_override=params_override # <--- NEW
        )]