#!/bin/bash

# 验证 agent-workflow Temporal 集成结构

echo "=== 验证 agent-workflow Temporal 集成结构 ==="

# 检查关键文件是否存在
echo "1. 检查关键文件:"
required_files=(
    "src/kardcraft/temporal/activities/agent_activities.py"
    "temporal/worker.py"
    "src/kardcraft/workflow/temporal_adapter.py"
    "src/kardcraft/workflow/manager_enhanced.py"
    ".env.example"
)

for file in "${required_files[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✓ $file"
    else
        echo "  ✗ $file (缺失)"
    fi
done

echo ""
echo "2. 检查 Temporal Activity 定义:"
if [ -f "src/kardcraft/temporal/activities/agent_activities.py" ]; then
    if grep -q "class AgentActivities" src/kardcraft/temporal/activities/agent_activities.py; then
        echo "  ✓ AgentActivities 类存在"
    else
        echo "  ✗ AgentActivities 类缺失"
    fi

    if grep -q "@activity.defn" src/kardcraft/temporal/activities/agent_activities.py; then
        echo "  ✓ Activity 装饰器存在"
    else
        echo "  ✗ Activity 装饰器缺失"
    fi
fi

echo ""
echo "3. 检查 Temporal Worker:"
if [ -f "temporal/worker.py" ]; then
    if grep -q "class Config" temporal/worker.py; then
        echo "  ✓ Config 类导入正确"
    else
        echo "  ✗ Config 类导入问题"
    fi

    if grep -q "async def run_worker" temporal/worker.py; then
        echo "  ✓ run_worker 函数存在"
    else
        echo "  ✗ run_worker 函数缺失"
    fi
fi

echo ""
echo "4. 检查 LangGraph 适配器:"
if [ -f "src/kardcraft/workflow/temporal_adapter.py" ]; then
    if grep -q "class TemporalLangGraphAdapter" src/kardcraft/workflow/temporal_adapter.py; then
        echo "  ✓ TemporalLangGraphAdapter 类存在"
    else
        echo "  ✗ TemporalLangGraphAdapter 类缺失"
    fi
fi

echo ""
echo "5. 检查配置:"
if [ -f ".env.example" ]; then
    if grep -q "TEMPORAL_ENDPOINT" .env.example; then
        echo "  ✓ TEMPORAL_ENDPOINT 配置存在"
    else
        echo "  ✗ TEMPORAL_ENDPOINT 配置缺失"
    fi

    if grep -q "TEMPORAL_TASK_QUEUE" .env.example; then
        echo "  ✓ TEMPORAL_TASK_QUEUE 配置存在"
    else
        echo "  ✗ TEMPORAL_TASK_QUEUE 配置缺失"
    fi
fi

echo ""
echo "6. 检查依赖:"
if [ -f "pyproject.toml" ]; then
    if grep -q "temporalio" pyproject.toml; then
        echo "  ✓ temporalio 依赖存在"
    else
        echo "  ✗ temporalio 依赖缺失"
    fi
fi

echo ""
echo "=== 验证完成 ==="