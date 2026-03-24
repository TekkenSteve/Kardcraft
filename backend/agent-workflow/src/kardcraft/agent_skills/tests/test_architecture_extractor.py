"""
Test architecture extractor skill with DeepAgents.

Copied from archive/DeepAgents-Skills/test_architecture_extractor.py

Run with:
    python -m kardcraft.agent_skills.tests.test_architecture_extractor
    
Or in background:
    python -m kardcraft.agent_skills.tests.test_architecture_extractor > output.log 2>&1 &
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI
from deepagents.backends import FilesystemBackend, CompositeBackend, StoreBackend

from kardcraft.agent_skills import SkillsMiddleware, NoSkillsMiddleware, ShellMiddleware
from .prompt import SYSTEM_PROMPT

# === Logging ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# === Load environment ===
load_dotenv()

# === Config ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
RECURSION_LIMIT = int(os.getenv("RECURSION_LIMIT", 25))

logging.info("✅ 系统提示词已加载")


def make_backend(runtime):
    routes = {
        "/fs/": FilesystemBackend(root_dir="./fs", virtual_mode=True),
    }
    
    # 只有当 runtime 中有 store 时才添加 /memories/ 路由
    if hasattr(runtime, 'store') and runtime.store is not None:
        routes["/memories/"] = StoreBackend(runtime)
    
    return CompositeBackend(
        default=FilesystemBackend(),
        routes=routes
    )


# === 创建模型实例 ===
model = ChatOpenAI(
    model=OPENAI_MODEL,
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL
)


# === Skills 配置 ===
USER_SKILLS_DIR = os.path.join(
    str(Path(__file__).parent.resolve()), 
    "architecture-extractor"
)
WORKSPACE_ROOT = str(Path(__file__).parent.resolve())


skills_middleware = SkillsMiddleware(
    skills_dir=USER_SKILLS_DIR,
    assistant_id="agent",
    project_skills_dir=None,
    name="architecture-extractor"
)

requirement_middleware = NoSkillsMiddleware(
    name="requirement-extractor"
)
usecase_middleware = NoSkillsMiddleware(
    name="usecase-extractor"
)
action_middleware = NoSkillsMiddleware(
    name="action-extractor"
)
state_middleware = NoSkillsMiddleware(
    name="state-extractor"
)
bdd_middleware = NoSkillsMiddleware(
    name="bdd-extractor"
)
ibd_middleware = NoSkillsMiddleware(
    name="ibd-extractor"
)

# === Shell 中间件配置 ===
shell_middleware = ShellMiddleware(
    workspace_root=WORKSPACE_ROOT,
    timeout=120.0,
    max_output_bytes=100000,
)

logging.info(f"✅ Skills 中间件已配置")
logging.info(f"  - 用户 Skills 目录: {USER_SKILLS_DIR}")
logging.info(f"✅ Shell 中间件已配置")
logging.info(f"  - 工作目录: {WORKSPACE_ROOT}")


# === 加载各视图的提示词文件 ===
def load_prompt_file(view_name):
    """加载指定视图的提示词文件"""
    prompt_path = os.path.join(
        USER_SKILLS_DIR, 
        f"{view_name}_prompt.md"
    )
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logging.error(f"无法加载提示词文件 {prompt_path}: {e}")
        return f"你是{view_name}视图信息提取器。"


# 加载各视图的提示词
requirement_prompt = load_prompt_file("requirement")
usecase_prompt = load_prompt_file("usecase")
action_prompt = load_prompt_file("action")
state_prompt = load_prompt_file("state")
bdd_prompt = load_prompt_file("bdd")
ibd_prompt = load_prompt_file("ibd")

logging.info("✅ 各视图提示词已加载")


# === 创建子智能体 ===
requirement_subagent = {
    "name": "requirement-extractor",
    "description": "需求图视图信息提取智能体，从用户输入中提取需求相关信息",
    "system_prompt": requirement_prompt,
    "tools": [],
    "model": model,
    "middleware": [requirement_middleware]  
}

usecase_subagent = {
    "name": "usecase-extractor",
    "description": "用例图视图信息提取智能体，从用户输入中提取用例相关信息",
    "system_prompt": usecase_prompt,
    "tools": [],
    "model": model,
    "middleware": [usecase_middleware]  
}

action_subagent = {
    "name": "action-extractor",
    "description": "活动图视图信息提取智能体，从用户输入中提取活动相关信息",
    "system_prompt": action_prompt,
    "tools": [],
    "model": model,
    "middleware": [action_middleware]
}

state_subagent = {
    "name": "state-extractor",
    "description": "状态机图视图信息提取智能体，从用户输入中提取状态相关信息",          
    "system_prompt": state_prompt,
    "tools": [],
    "model": model,
    "middleware": [state_middleware]
}

bdd_subagent = {
    "name": "bdd-extractor",
    "description": "模块定义图视图信息提取智能体，从用户输入中提取模块定义相关信息",
    "system_prompt": bdd_prompt,
    "tools": [],
    "model": model,
    "middleware": [bdd_middleware]
}

ibd_subagent = {
    "name": "ibd-extractor",
    "description": "内部模块图视图信息提取智能体，从用户输入中提取内部模块相关信息",
    "system_prompt": ibd_prompt,
    "tools": [],
    "model": model,
    "middleware": [ibd_middleware]
}

agent = create_deep_agent(
    model=model,
    tools=[],
    subagents=[
        requirement_subagent,
        usecase_subagent,
        action_subagent,
        state_subagent,
        bdd_subagent,
        ibd_subagent
    ],
    backend=make_backend,
    middleware=[skills_middleware, shell_middleware],
    system_prompt=SYSTEM_PROMPT,
    debug=True
).with_config({"recursion_limit": RECURSION_LIMIT})

logging.info(f"✅ DeepAgent 已创建")
logging.info(f"  - 模型: {OPENAI_MODEL}")
logging.info(f"  - 递归限制: {RECURSION_LIMIT}")


# === 测试运行 ===
if __name__ == "__main__":
    # query = "工作温度：-5℃到10℃"    # 需求+用例
    # query = "飞控系统的参与者有飞行员"  # 用例
    query = "燃油从打开油箱传递到打开发动机"  # 活动+ibd
    
    logging.info(f"\n{'='*60}")
    logging.info(f"开始分析: {query}")
    logging.info(f"{'='*60}\n")
    
    try:
        # 运行 agent
        result = agent.invoke({"messages": [{"role": "user", "content": query}]})
        
        # 输出结果
        print("\n" + "="*60)
        print("分析结果：")
        print("="*60 + "\n")
        
        # 获取最后一条消息
        if result and "messages" in result:
            last_message = result["messages"][-1]
            if hasattr(last_message, "content"):
                content = last_message.content if hasattr(last_message, "content") else str(last_message)
                print(content)

                # 保存结果到文件
                from datetime import datetime

                # 创建结果目录
                result_dir = "./result"
                if not os.path.exists(result_dir):
                    os.makedirs(result_dir)

                # 生成时间戳文件名
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(result_dir, f"{timestamp}.md")

                # 写入文件
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(content)

                print(f"\n结果已保存到: {filename}")
            else:
                print(last_message)
        else:
            print("未获取到分析结果")
            
    except Exception as e:
        logging.error(f"分析过程中出错: {str(e)}", exc_info=True)
