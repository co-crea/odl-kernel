# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from typing import List, Dict, Any, Tuple, Set

from odl_kernel.types import ProcessNode, LifecycleStatus, BusinessResult
from .base import ExpansionStrategy, ExpansionPlan


class IterateExpansionStrategy(ExpansionStrategy):
    """
    [Strategy] Iterate Expansion Logic (Data-Driven & Hybrid Strategy)

    Architecture:
        L3 Mechanism (Logic) - Pure Domain Logic

    Responsibility:
        データソース（Items）の各要素に対し、単一のBlueprint（contents）を適用して展開する。
        展開のタイミング（順序）は `strategy` パラメータ ("serial" | "parallel") によって制御される。

    Path Resolution (Strict Inheritance & Key Insertion):
        Iterateは階層構造に「データキーに基づくセグメント ({Key})」を物理的に挿入する。
        Blueprintの stack_path は使用せず、「親パス」 + 「キー({Key})」 + 「ノード名」 を結合して物理パスを構築する。
        Format: "{ParentPath}/{Key}/{NodeName}"

    Context Injection:
        子ノードに対し、以下の変数を注入する：
        - `$KEY`: 現在の展開キー (String)
        - `$ITEM`: 現在のデータ実体
        - `$LOOP`: 現在のインデックス (1-based integer)
        - `$PREV`: [Serial専用] 直前のイテレーションの成果物識別子 (default/{Key})
        - `$HISTORY`: [Serial専用] これまでの全イテレーションの成果物識別子リスト (List[str])

    Exit/Wait Conditions (Serial Mode):
        1. System Failure: 直前のノードが FAILED した場合、即座に停止する。
        2. Business Error: 直前のノードが ERROR の場合、即座に停止する。
        3. Completion Wait: 直前のノードが完了するまで待機する。
    """

    def plan_next_nodes(
        self,
        parent: ProcessNode,
        current_children: List[ProcessNode]
    ) -> List[ExpansionPlan]:
        """
        Args:
            parent: 親ノード。paramsに 'strategy', 'items' を持つ。
            current_children: 生成済みの子ノードリスト。

        Returns:
            List[ExpansionPlan]: 次に生成すべきノードの計画リスト。
        """
        if not parent.children_blueprint:
            return []

        # IterateのBlueprintは常に1つ (contentsブロック)
        body_blueprint = parent.children_blueprint[0]
        raw_items = parent.params.get("items", {})

        target_entries: List[Tuple[str, Any]] = []
        if isinstance(raw_items, dict):
            target_entries = list(raw_items.items())
        elif isinstance(raw_items, list):
            # List形式（Tupleリスト等）の場合の正規化
            target_entries = raw_items

        if not target_entries:
            return []

        strategy_mode = parent.params.get("strategy", "serial")

        if strategy_mode == "parallel":
            return self._plan_parallel(parent, body_blueprint, target_entries, current_children)
        else:
            return self._plan_serial(parent, body_blueprint, target_entries, current_children)

    def _plan_serial(
        self,
        parent: ProcessNode,
        blueprint: Any,
        entries: List[Tuple[str, Any]],
        current_children: List[ProcessNode]
    ) -> List[ExpansionPlan]:
        """Serial Mode: 順次実行とコンテキスト・リレーの物理"""
        spawned_count = len(current_children)
        total_count = len(entries)

        # 全て展開済みなら終了
        if spawned_count >= total_count:
            return []

        # Wait & Status Check (Lifecycle Aware)
        if spawned_count > 0:
            last_child = current_children[-1]
            if last_child.lifecycle_status == LifecycleStatus.FAILED:
                return []
            if last_child.lifecycle_status != LifecycleStatus.COMPLETED:
                return []
            if last_child.business_result == BusinessResult.ERROR:
                return []

        # Target Entry
        key, value = entries[spawned_count]
        index = spawned_count + 1

        # --- [Physics] Context Relay Calculation ---
        # 過去のイテレーションのキーを収集し、PREVとHISTORYを構成する
        prev_key_id = None
        history_key_ids = []
        
        for i in range(spawned_count):
            k, _ = entries[i]
            # ODLの標準命名規則に従い、パーティション名(default)を付与した物理参照を生成
            partitioned_id = f"default/{k}"
            history_key_ids.append(partitioned_id)
            prev_key_id = partitioned_id

        return [self._create_plan(
            parent, blueprint, key, value, index,
            prev_key=prev_key_id,
            history_keys=history_key_ids
        )]

    def _plan_parallel(
        self,
        parent: ProcessNode,
        blueprint: Any,
        entries: List[Tuple[str, Any]],
        current_children: List[ProcessNode]
    ) -> List[ExpansionPlan]:
        """Parallel Mode: 一括生成（収束ロジック）"""
        plans: List[ExpansionPlan] = []
        existing_paths: Set[str] = {child.stack_path for child in current_children}

        for i, (key, value) in enumerate(entries):
            index = i + 1
            node_name = self._get_node_name(blueprint)
            expected_path = f"{parent.stack_path}/{key}/{node_name}"

            if expected_path not in existing_paths:
                plans.append(self._create_plan(parent, blueprint, key, value, index))

        return plans

    def _create_plan(
        self,
        parent: ProcessNode,
        blueprint: Any,
        key: str,
        value: Any,
        index: int,
        prev_key: str = None,
        history_keys: List[str] = None
    ) -> ExpansionPlan:
        """共通のパス解決・コンテキスト注入ロジック"""
        node_name = self._get_node_name(blueprint)
        resolved_path = f"{parent.stack_path}/{key}/{node_name}"

        context_vars = {
            "$KEY": key,
            "$ITEM": value,
            "$LOOP": index
        }
        
        # [Relay Physics] リレー変数の注入
        if prev_key:
            context_vars["$PREV"] = prev_key
        if history_keys:
            context_vars["$HISTORY"] = history_keys

        return ExpansionPlan(
            blueprint=blueprint,
            context_vars=context_vars,
            resolved_path=resolved_path,
            original_index=0
        )