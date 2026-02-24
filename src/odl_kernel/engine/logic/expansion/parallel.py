# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from typing import List, Set

from odl_kernel.types import ProcessNode, LifecycleStatus, BusinessResult
from .base import ExpansionStrategy, ExpansionPlan

class ParallelExpansionStrategy(ExpansionStrategy):
    """
    Parallel Expansion Logic (Target State Convergence)
    
    Architecture:
        L3 Mechanism (Logic) - Pure Domain Logic
    
    Responsibility:
        定義された子ノード群（Blueprint）と、現在の子ノード群（Current Children）を比較し、
        「欠落しているノード」のみを展開計画に追加する（Batch / Diff-based Expansion）。
        
        この「収束（Convergence）」アプローチにより、以下の要件を満たす：
        1. Resilience: 生成プロセスが中断した場合でも、次のTickで不足分のみを自動的に補完する。
        2. Resume Compatibility: Resumeプロトコルにより既存ノードがPENDING等にロールバックされた場合、
           それらは「存在する」とみなされ、重複生成（SPAWN）が防止される。
    
    Path Resolution (Strict Inheritance):
        Blueprintの `stack_path` は未解決トークンを含む可能性があるため、信頼せず使用しない。
        必ず「親の解決済みパス (`parent.stack_path`)」と「自身のノード名」を結合し、
        親の実行コンテキスト（v1, key等）を継承した物理パスを生成する。
    
    Context & Data:
        Parallel展開においてはコンテキスト変数の注入は発生しない。
        兄弟間のデータ依存は Wiring 定義によって明示的に解決される。
    """

    def plan_next_nodes(
        self, 
        parent: ProcessNode, 
        current_children: List[ProcessNode]
    ) -> List[ExpansionPlan]:
        """
        Args:
            parent: 親ノード（Blueprints, Resolved Path保持）
            current_children: 既に生成されている子ノードのリスト（順不同可）
        
        Returns:
            List[ExpansionPlan]: 新規に生成すべきノードの計画リスト。
                                 全て生成済みの場合は空リストを返す。
        """
        blueprints = parent.children_blueprint
        if not blueprints:
            return []

        # 1. Map Existing Children Paths
        # 高速な照合のため、現在の子ノードのパスをSet化する。
        # Resume/Recovery時、StatusがFAILEDやPENDINGであっても「DBにレコードがある」ならば再生成は不要。
        existing_paths: Set[str] = {child.stack_path for child in current_children}

        plans: List[ExpansionPlan] = []

        # 2. Convergence Evaluation with Index
        # enumerateを使用して、Blueprintリスト上の正確なインデックス(original_index)を取得する。
        # これは後続のSPAWN_CHILDコマンド生成時に必須となる。
        for i, bp in enumerate(blueprints):
            
            # 3. Path Resolution (Strict)
            # Logic: ParentResolvedPath + "/" + NodeName
            # Blueprintパス内のトークンに依存せず、親の確定パスを継承する。
            node_name = self._get_node_name(bp)
            resolved_path = f"{parent.stack_path}/{node_name}"
            
            # 4. Missing Check (Diff)
            # 存在しない（欠落している）場合のみ計画に追加する
            if resolved_path not in existing_paths:
                plans.append(ExpansionPlan(
                    blueprint=bp,
                    context_vars={}, # Context注入なし
                    resolved_path=resolved_path,
                    original_index=i # 定義上の位置を保持
                ))
        
        return plans