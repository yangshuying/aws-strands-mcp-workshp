#!/usr/bin/env python3
"""
MCP Server for Rule Query Workflow
基于MCP协议的规则查询服务器实现
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
import requests

from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rule-query-mcp-server")

# 创建MCP服务器实例
server = Server("rule-query-server")

class RuleQueryService:
    """规则查询服务类"""
    
    @staticmethod
    async def fetch_order_status(order_id: str) -> Dict[str, Any]:
        """获取订单状态"""
        url = "https://1m9r5sk109.execute-api.cn-northwest-1.amazonaws.com.cn/prod/kit_box/order_status"
        
        try:
            # 在实际的异步环境中，应该使用aiohttp等异步HTTP库
            # 这里为了简化，仍使用requests（在生产环境中应该替换）
            response = requests.get(url, params={"order_id": order_id}, timeout=10)
            logger.info(f"Order status response: {response.json()}")
            return {
                "status_code": response.status_code,
                "body": response.json() if response.status_code == 200 else {}
            }
        except Exception as e:
            logger.error(f"Error fetching order status: {e}")
            return {"status_code": 500, "body": {}}

    @staticmethod
    async def fetch_matched_rules(purpose: str) -> Dict[str, Any]:
        """获取匹配的规则"""
        url = "https://1m9r5sk109.execute-api.cn-northwest-1.amazonaws.com.cn/prod/purpose"
        
        try:
            response = requests.get(url, params={"purpose": purpose}, timeout=10)
            logger.info(f"Matched rules response: {response.json()}")
            return response.json() if response.status_code == 200 else {}
        except Exception as e:
            logger.error(f"Error fetching matched rules: {e}")
            return {}

    @staticmethod
    def filter_rules(rules: Dict[str, Any], order_status: Dict[str, Any]) -> str:
        """过滤规则（简化版本）"""
        
        if not rules:
            return json.dumps({"规则": "未找到匹配的规则"}, ensure_ascii=False)
        
        # 简单的规则匹配逻辑
        filtered_rules = {}
        
        # 根据订单状态过滤规则
        order_body = order_status.get('body', {})
        
        if isinstance(rules, dict):
            for key, value in rules.items():
                # 简单的匹配逻辑
                if RuleQueryService.should_include_rule(key, value, order_body):
                    filtered_rules[key] = value
        
        return json.dumps({"规则": filtered_rules}, ensure_ascii=False, indent=2)

    @staticmethod
    def should_include_rule(rule_key: str, rule_value: Any, order_info: Dict) -> bool:
        """判断是否应该包含某个规则"""
        
        if not order_info:
            return True
        
        # 示例：根据订单状态决定规则适用性
        order_status = order_info.get('status', '').lower()
        rule_key_lower = str(rule_key).lower()
        
        # 一些简单的匹配规则
        if 'cancel' in rule_key_lower and order_status in ['pending', 'confirmed']:
            return True
        elif 'modify' in rule_key_lower and order_status in ['pending']:
            return True
        elif 'query' in rule_key_lower:
            return True
        
        return True  # 默认包含所有规则

    @staticmethod
    async def rule_query_workflow(order_id: str, purpose: str) -> Dict[str, Any]:
        """
        基于rule_query.yml的简化工作流实现
        
        工作流步骤：
        1. 获取订单状态
        2. 判断订单是否存在（状态码200）
        3. 如果存在：获取匹配规则 -> LLM过滤 -> 返回结果
        4. 如果不存在：返回错误信息
        
        Args:
            order_id: 订单ID
            purpose: 查询目的
            
        Returns:
            查询结果
        """
        
        # Step 1: 获取订单状态
        order_status = await RuleQueryService.fetch_order_status(order_id)
        
        # Step 2: 判断订单是否存在
        if order_status and order_status.get('status_code') == 200:
            # 订单存在，继续处理
            matched_rules = await RuleQueryService.fetch_matched_rules(purpose)
            
            if matched_rules:
                # Step 3: 过滤规则
                filtered_result = RuleQueryService.filter_rules(matched_rules, order_status)
                return {"text": filtered_result}
            else:
                return {"error": "Failed to get matched rules"}
        else:
            # 订单不存在
            return {"result": "order_id is not exist, please check"}

# MCP服务器工具定义
@server.list_tools()
async def handle_list_tools() -> ListToolsResult:
    """
    列出可用的工具
    """
    return ListToolsResult(
        tools=[
            Tool(
                name="rule_query_workflow",
                description="执行规则查询工作流，根据订单ID和查询目的获取相关规则",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "description": "订单ID"
                        },
                        "purpose": {
                            "type": "string", 
                            "description": "查询目的，例如：修改配送时间、取消订单等"
                        }
                    },
                    "required": ["order_id", "purpose"]
                }
            ),
            Tool(
                name="fetch_order_status",
                description="获取指定订单的状态信息",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "description": "订单ID"
                        }
                    },
                    "required": ["order_id"]
                }
            ),
            Tool(
                name="fetch_matched_rules",
                description="根据查询目的获取匹配的规则",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "purpose": {
                            "type": "string",
                            "description": "查询目的"
                        }
                    },
                    "required": ["purpose"]
                }
            )
        ]
    )

@server.call_tool()
async def handle_call_tool(request: CallToolRequest) -> CallToolResult:
    """
    处理工具调用请求
    """
    try:
        if request.name == "rule_query_workflow":
            # 执行完整的规则查询工作流
            order_id = request.arguments.get("order_id")
            purpose = request.arguments.get("purpose")
            
            if not order_id or not purpose:
                return CallToolResult(
                    content=[TextContent(
                        type="text",
                        text="错误：缺少必需参数 order_id 或 purpose"
                    )],
                    isError=True
                )
            
            result = await RuleQueryService.rule_query_workflow(order_id, purpose)
            
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(result, ensure_ascii=False, indent=2)
                )]
            )
            
        elif request.name == "fetch_order_status":
            # 获取订单状态
            order_id = request.arguments.get("order_id")
            
            if not order_id:
                return CallToolResult(
                    content=[TextContent(
                        type="text",
                        text="错误：缺少必需参数 order_id"
                    )],
                    isError=True
                )
            
            result = await RuleQueryService.fetch_order_status(order_id)
            
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(result, ensure_ascii=False, indent=2)
                )]
            )
            
        elif request.name == "fetch_matched_rules":
            # 获取匹配规则
            purpose = request.arguments.get("purpose")
            
            if not purpose:
                return CallToolResult(
                    content=[TextContent(
                        type="text",
                        text="错误：缺少必需参数 purpose"
                    )],
                    isError=True
                )
            
            result = await RuleQueryService.fetch_matched_rules(purpose)
            
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(result, ensure_ascii=False, indent=2)
                )]
            )
            
        else:
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=f"未知工具: {request.name}"
                )],
                isError=True
            )
            
    except Exception as e:
        logger.error(f"Tool execution error: {e}")
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=f"工具执行错误: {str(e)}"
            )],
            isError=True
        )

async def main():
    """主函数 - 启动MCP服务器"""
    # 使用stdio传输启动服务器
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="rule-query-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())
