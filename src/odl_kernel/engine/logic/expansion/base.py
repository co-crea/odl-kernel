# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from odl.types import IrComponent
from odl_kernel.types import ProcessNode

@dataclass
class ExpansionPlan:
    """
    ExpansionStrategyが導出する「次の一手」の定義。
    Analyzeフェーズの出力であり、RuntimeCommand (SPAWN_CHILD) の生成源となる。
    """
    blueprint: IrComponent            # 実体化すべきノードの定義 (IR)
    context_vars: Dict[str, Any]      # 注入すべきコンテキスト変数 ($LOOP, $PREV 等)
    resolved_path: str                # トークン解決済みの物理パス (ID生成の種)
    original_index: int               # 親のchildren_blueprintリストにおけるインデックス (Selector用)
    
    # 動的に取得したデータ(items等)を注入するために使用する
    params_override: Optional[Dict[str, Any]] = None

class ExpansionStrategy(ABC):
    """
    Expansion Logic Interface
    
    Architecture:
        L3 Mechanism (Logic) - Pure Domain Logic
    
    Responsibility:
        親ノードの状態と、現在の子ノード群（Current Children）に基づき、
        「次に生成すべき子ノード」の計画（ExpansionPlan）を立案する。
        
        具体的な展開ロジック（順次、一括、反復等）は、継承先の各Strategyクラスで定義される。
        StrategyはDBへの書き込みや副作用を持たず、純粋に計画オブジェクトを返すことに徹する。
    """

    @abstractmethod
    def plan_next_nodes(
        self, 
        parent: ProcessNode, 
        current_children: List[ProcessNode]
    ) -> List[ExpansionPlan]:
        """
        Args:
            parent: 親ノード（Blueprints, Resolved Path保持）
            current_children: 既に生成されている子ノードのリスト
        
        Returns:
            List[ExpansionPlan]: 新規に生成すべきノードの計画リスト。
                                 生成すべきものがなければ空リストを返す。
        """
        pass

    def _get_node_name(self, blueprint: IrComponent) -> str:
        """
        Blueprintのパスから、末尾のノード名部分のみを抽出するヘルパーメソッド。
        
        Usage:
            Strict Path Resolution (Inheritance) のために使用される。
            Blueprint全体のパス（未解決トークンを含む可能性がある）ではなく、
            このメソッドで得た名前を親パスに結合することで、安全な物理パスを生成する。
            
            Example: "root/loop/v{$LOOP}/worker_0" -> "worker_0"
        """
        return blueprint.stack_path.split("/")[-1]