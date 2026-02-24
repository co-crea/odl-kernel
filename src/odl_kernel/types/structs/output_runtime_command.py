# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from typing import Any, Dict
from pydantic import BaseModel, Field

from .output_command_type import CommandType

class RuntimeCommand(BaseModel):
    """
    ノードに対する副作用（Side Effects）の実行指示書。
    Kernel自身はこれを実行せず、Cortex（Host）がこれを受け取って物理的に処理する。
    """
    type: CommandType
    target_node_id: str
    
    # コマンド固有のパラメータ (e.g. {"to_status": "COMPLETED"})
    payload: Dict[str, Any] = Field(default_factory=dict)