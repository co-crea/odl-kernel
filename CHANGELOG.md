# Changelog

All notable changes to this project will be documented in this file.

## [0.9.0] - 2026-02-24
### Added
- **Initial Public Release** of the ODL Kernel, the reference "Physics Engine" for agent organizations.
- **Functional Core Analyzer**: Side-effect-free execution engine that derives next states from a `JobSnapshot` and `KernelEvent`.
- **Deep Analyze Mechanism**: Implementation of fixed-point iteration to advance organizational states until stable equilibrium is reached.
- **Deterministic ID Generator**: UUID v5-based identity generation using structural paths, proprietary origin salt, and watermarking for provenance tracking.
- **Dynamic Variable Resolver**: Support for runtime context injection and arithmetic filtering for tokens including `$LOOP`, `$KEY`, `$PREV`, and `$HISTORY`.
- **Expansion Strategies**: Implementation of lazy and batch expansion logic for `serial`, `parallel`, `loop`, and `iterate` (fan-out) primitives.
- **Advanced Transition Rules**:
    - Failure propagation logic (Fail Fast for serial, Graceful Wait for parallel).
    - Self-driving behaviors for Control and Logic nodes.
    - Output aggregation and business result reconciliation.
- **Scenario-Based Test Suite**: Over 20 integration test scenarios covering complex organizational patterns, feedback loops, and asynchronous data resolution.
- **Host Abstraction**: Interface for Host Runtime side-effects via `RuntimeCommand` (DISPATCH, REQUIRE_DATA, etc.).