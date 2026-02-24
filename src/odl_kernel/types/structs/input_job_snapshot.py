# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from typing import Dict
from pydantic import BaseModel, Field

from ..entities import Job, ProcessNode

class JobSnapshot(BaseModel):
    """
    ODLカーネルへの入力：ある瞬間における「世界の全て」。
    DBからロードしたJobとNodeの集合体を、このオブジェクトに詰め替えて渡す。
    これにより、KernelはDBにアクセスすることなく計算を行える。
    """
    job: Job
    
    # 高速な参照のためにMap形式(str -> Node)で保持する
    nodes: Dict[str, ProcessNode] = Field(default_factory=dict)

    @property
    def root_node(self) -> ProcessNode | None:
        """ルートノードへのショートカットアクセサ"""
        if self.job.root_node_id:
            return self.nodes.get(self.job.root_node_id)
        return None