#!/usr/bin/env python3
import json
import requests
import os
import re
from typing import Optional, Dict, Any, List
from mcp.server.fastmcp import FastMCP, Context
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# 创建MCP服务器实例
mcp = FastMCP("data-preprocess-server")

# 硅基流动 API 配置
SILICONFLOW_CONFIG = {
    "api_url": "https://api.siliconflow.cn/v1/chat/completions",
    "model": "deepseek-ai/DeepSeek-V3",
    "max_tokens": 2000,
    "timeout": 60
}

# 订单分类API配置
CATEGORY_API_URL = "https://1m9r5sk109.execute-api.cn-northwest-1.amazonaws.com.cn/prod/category"

def get_local_tz(local_tz_override: str | None = None) -> ZoneInfo:
    # Get local timezone from datetime.now()
    tzinfo = datetime.now().astimezone(tz=None).tzinfo
    if tzinfo is not None:
        tz_str = str(tzinfo)
        if tz_str == "CST":
            tz_str = "America/Chicago" 
        return ZoneInfo(tz_str)
    else:
        raise ValueError('get local timezone failed')

def update_docstring_with_info(func):
    """更新函数的docstring"""
    local_tz = str(get_local_tz())
    if func.__doc__:
        func.__doc__ = func.__doc__.format(local_tz=local_tz)
    return func

def get_categories() -> Optional[Dict[str, Any]]:
    """获取订单分类信息"""
    try:
        response = requests.get(CATEGORY_API_URL, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"HTTP请求失败: {e}")
        return None

def call_siliconflow_deepseek(messages: list, temperature: float = 0.7) -> Optional[str]:
    """调用硅基流动 DeepSeek API"""
    api_key = os.getenv('SILICONFLOW_API_KEY')
    if not api_key:
        raise ValueError("请设置环境变量 SILICONFLOW_API_KEY")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": SILICONFLOW_CONFIG["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": SILICONFLOW_CONFIG["max_tokens"],
        "stream": False
    }
    
    try:
        response = requests.post(
            SILICONFLOW_CONFIG["api_url"], 
            headers=headers, 
            json=payload, 
            timeout=SILICONFLOW_CONFIG["timeout"]
        )
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content']
    except requests.exceptions.RequestException as e:
        print(f"DeepSeek API调用失败: {e}")
        return None
    except (KeyError, IndexError) as e:
        print(f"解析API响应失败: {e}")
        return None

def simulate_llm_response(input_query: str) -> Dict[str, Any]:
    """模拟LLM响应（备用方案）"""
    # 查找订单号模式
    order_patterns = [
        r'订单号?\s*[：:]\s*([A-Za-z0-9]+)',
        r'订单\s*([A-Za-z0-9]+)',
        r'([A-Za-z0-9]{10,})'  # 假设订单号至少10位
    ]
    
    order_ids = []
    for pattern in order_patterns:
        matches = re.findall(pattern, input_query)
        order_ids.extend(matches)
    
    # 移除重复
    order_ids = list(set(order_ids))
    
    if not order_ids:
        return {"valid_question": "no"}
    
    # 简单的意图识别
    purposes = []
    if any(word in input_query for word in ['查询', '查看', '状态']):
        purposes.append('查询订单状态')
    if any(word in input_query for word in ['取消', '退订']):
        purposes.append('取消订单')
    if any(word in input_query for word in ['修改', '更改']):
        purposes.append('修改订单')
    
    if not purposes:
        purposes = ['查询订单状态']  # 默认意图
    
    task_count = max(len(order_ids), len(purposes))
    
    if task_count == 1:
        return {
            "valid_question": "yes",
            "multi-task": "no",
            "task_count": 1,
            "tasks": {
                "order_id_1": order_ids[0] if order_ids else "unknown",
                "purpose_1": purposes[0]
            }
        }
    else:
        result = {
            "valid_question": "yes",
            "multi-task": "yes",
            "task_count": task_count
        }
        
        for i in range(task_count):
            task_key = f"task_{i+1}"
            result[task_key] = {
                f"order_id_{i+1}": order_ids[i] if i < len(order_ids) else order_ids[-1],
                f"purpose_{i+1}": purposes[i] if i < len(purposes) else purposes[-1]
            }
        
        return result

def extract_tasks_with_deepseek(input_query: str, categories: Dict[str, Any]) -> Dict[str, Any]:
    """使用DeepSeek API从用户查询中提取订单任务信息"""
    system_prompt = f"""你是一个订单查询分析助手。你需要从用户的查询问题中提取订单相关任务，并将其分解为标准格式。

你需要遵循以下规则：
1. 意图库是categories in {json.dumps(categories, ensure_ascii=False)}
2. 每个task必须包含订单号(order_id)和具体意图(purpose)
3. 判断是否为有效问题(valid_question)：查询内容必须与意图库中的操作相关
4. 判断是否为多任务(multi-task)：包含多个订单号或多个意图时为true
5. 统计任务数量(task_count)：提取出的合法task数量
6. 按照固定格式输出结果，必须是有效的JSON格式

输出格式示例：
单任务：
{{
    "valid_question": "yes",
    "multi-task": "no",
    "task_count": 1,
    "tasks": {{
        "order_id_1": "xxx",
        "purpose_1": "xxx"
    }}
}}

多任务：
{{
    "valid_question": "yes",
    "multi-task": "yes",
    "task_count": 2,
    "task_1": {{
        "order_id_1": "xxx",
        "purpose_1": "xxx"
    }},
    "task_2": {{
        "order_id_2": "xxx",
        "purpose_2": "xxx"
    }}
}}

无效问题：
{{
    "valid_question": "no"
}}"""

    user_prompt = f"""请分析以下查询问题，提取订单任务信息：

{input_query}

请按照以下步骤进行分析，只输出最终的JSON结果：

1. 判断是否为有效的订单相关问题
2. 识别问题中的订单号和操作意图
3. 确认是否存在多任务情况
4. 统计任务数量
5. 按照规定格式输出结果"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    # 调用DeepSeek API
    response_content = call_siliconflow_deepseek(messages, temperature=0.7)
    
    if not response_content:
        # 如果API调用失败，使用备用方案
        return simulate_llm_response(input_query)
    
    try:
        # 尝试解析JSON响应
        # 清理响应内容，移除可能的markdown格式
        cleaned_content = response_content.strip()
        if cleaned_content.startswith('```json'):
            cleaned_content = cleaned_content[7:]
        if cleaned_content.endswith('```'):
            cleaned_content = cleaned_content[:-3]
        cleaned_content = cleaned_content.strip()
        
        result = json.loads(cleaned_content)
        return result
        
    except json.JSONDecodeError as e:
        print(f"JSON解析失败: {e}")
        print(f"原始响应: {response_content}")
        # 如果解析失败，使用备用方案
        return simulate_llm_response(input_query)

@mcp.tool()
def data_preprocess(input_query: str) -> str:
    """
    数据预处理工具，从用户查询中提取订单任务信息
    
    Args:
        input_query: 用户输入的查询问题，例如："我要调整订单ST-9012的配送时间"
        
    Returns:
        str: JSON格式的任务摘要，包含订单号、意图、任务数量等信息
    """
    try:
        # Step 1: 获取分类信息
        categories_response = get_categories()
        if not categories_response:
            return json.dumps({"error": "Failed to fetch categories"}, ensure_ascii=False)
        
        # Step 2: LLM处理 - 任务提取
        task_summary = extract_tasks_with_deepseek(input_query, categories_response)
        return json.dumps(task_summary, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({"error": f"Task extraction failed: {str(e)}"}, ensure_ascii=False)

@mcp.tool()
def get_order_categories() -> str:
    """
    获取订单分类信息
    
    Returns:
        str: JSON格式的分类信息
    """
    try:
        categories = get_categories()
        if categories:
            return json.dumps(categories, ensure_ascii=False, indent=2)
        else:
            return json.dumps({"error": "Failed to fetch categories"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to get categories: {str(e)}"}, ensure_ascii=False)

@mcp.tool()
def simulate_task_extraction(input_query: str) -> str:
    """
    模拟任务提取（不调用外部API的备用方案）
    
    Args:
        input_query: 用户输入的查询问题
        
    Returns:
        str: JSON格式的模拟任务提取结果
    """
    try:
        result = simulate_llm_response(input_query)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Simulation failed: {str(e)}"}, ensure_ascii=False)

if __name__ == "__main__":
    #mcp.run()
    # 设置API密钥（实际使用时应该从环境变量获取）
    # os.environ['SILICONFLOW_API_KEY'] = 'your_api_key_here'
    
    # 测试用例
    test_queries = [
        "我要调整订单ST-9012的配送时间",
        "今天天气怎么样？"  # 无效问题
    ]
    
    for query in test_queries:
        print(f"\n查询: {query}")
        result = data_preprocess(query)
        print(f"结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
        print("-" * 50)

    