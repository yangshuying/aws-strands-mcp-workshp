#!/usr/bin/env python3

"""
S3 Download Agent - 从S3下载文件并使用Strands Agents SDK读取文件内容

这个模块实现了一个智能简历分析系统，主要功能包括：
1. 从AWS S3存储桶中获取简历文件列表
2. 下载并解析简历文件内容（支持多种格式）
3. 使用AI Agent对简历进行智能分析和评估
4. 生成标准化的JSON格式评估报告

主要组件：
- S3DownloadAgent: 负责S3文件操作的代理类
- traverse_list_content: 遍历和处理S3对象列表的核心函数
- AI Agent: 基于Strands框架的智能分析代理

使用场景：
- 人力资源部门批量处理求职简历
- 自动化简历筛选和初步评估
- 简历内容结构化提取和分析
"""

import os
import tempfile
import logging
import ast
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import boto3
from markitdown import MarkItDown  # 用于将各种文档格式转换为Markdown
from strands import Agent
from strands.models.openai import OpenAIModel
from strands.models.litellm import LiteLLMModel
from strands_tools import use_aws, file_read, swarm, calculator

# 配置日志系统，用于记录程序运行状态和调试信息
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_aws_credentials() -> Dict[str, str]:
    """
    从环境变量中获取AWS凭证信息
    
    该函数用于安全地获取AWS访问凭证，支持以下环境变量：
    - AWS_ACCESS_KEY_ID: AWS访问密钥ID（必需）
    - AWS_SECRET_ACCESS_KEY: AWS秘密访问密钥（必需）
    - AWS_SESSION_TOKEN: AWS会话令牌（可选，用于临时凭证）
    
    Returns:
        Dict[str, str]: 包含AWS凭证的字典，如果必需的凭证缺失则返回None
        
    Note:
        这种方式比硬编码凭证更安全，符合AWS安全最佳实践
    """
    # 从环境变量获取AWS凭证
    access_key = os.environ.get('AWS_ACCESS_KEY_ID')
    secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
    session_token = os.environ.get('AWS_SESSION_TOKEN')  # 可选，用于临时凭证
    
    # 检查必需的凭证是否存在
    if not access_key or not secret_key:
        return None
    
    # 构建凭证字典
    credentials = {
        'aws_access_key_id': access_key,
        'aws_secret_access_key': secret_key
    }
    
    # 如果存在会话令牌，则添加到凭证中
    if session_token:
        credentials['aws_session_token'] = session_token
        
    return credentials

# 注意：此类目前未被使用（由Amazon Q生成但未集成到主流程中）
class S3DownloadAgent:
    """
    S3文件下载和读取代理类
    
    这个类封装了与AWS S3交互的功能，包括：
    - 列出S3存储桶中的对象
    - 下载S3文件到本地临时目录
    - 使用Strands Agent读取和分析文件内容
    - 自动管理临时文件的清理
    
    设计模式：
    - 使用上下文管理器模式，确保资源自动清理
    - 集成Strands Agent框架，提供AI分析能力
    
    注意：当前版本中此类未被主流程使用，主要功能通过全局agent实现
    """
    
    def __init__(self, aws_region: str = 'us-east-1'):
        """
        初始化S3下载代理
        
        Args:
            aws_region (str): AWS区域，默认为us-east-1
                            根据实际S3存储桶位置选择合适的区域
        """
        self.aws_region = aws_region
        self.temp_dir = None  # 临时目录路径，用于存储下载的文件
        self.agent = None     # Strands Agent实例
        
        # 初始化Strands Agent和相关资源
        self._init_agent()
    
    def _init_agent(self):
        """
        初始化Strands Agent和临时目录
        
        该方法执行以下操作：
        1. 创建临时目录用于存储下载的文件
        2. 初始化Strands Agent，配置必要的工具
        3. 记录初始化状态
        
        Raises:
            Exception: 如果初始化过程中出现错误
        """
        try:
            # 创建临时目录，使用特定前缀便于识别和管理
            self.temp_dir = tempfile.mkdtemp(prefix="s3_download_")
            logger.info(f"创建临时目录: {self.temp_dir}")
            
            # 初始化Agent，配置AWS操作、文件读取和协作工具
            self.agent = Agent(tools=[use_aws, file_read, swarm])
            logger.info("Strands Agent初始化成功")
            
        except Exception as e:
            logger.error(f"初始化Strands Agent失败: {e}")
            raise
    
    def list_s3_objects_with_agent(self, bucket_name: str, prefix: str = "") -> Dict[str, Any]:
        """
        使用Agent列出S3存储桶中指定前缀的对象
        
        该方法通过Strands Agent调用AWS S3 API来获取对象列表，
        并对返回结果进行类型检查和内容分析。
        
        Args:
            bucket_name (str): S3存储桶名称
            prefix (str): 对象前缀（相当于文件夹路径），默认为空字符串
            
        Returns:
            Dict[str, Any]: 包含以下字段的字典：
                - raw_result: 原始API调用结果
                - content: 解析后的内容
                - content_type: 内容类型名称
                - traversal_result: 如果内容是列表，包含遍历分析结果
                - message: 如果内容不是列表类型的说明信息
                
        Raises:
            Exception: 如果S3 API调用失败
        """
        try:
            # 使用Agent调用AWS S3 list_objects_v2 API
            result = self.agent.tools.use_aws(
                service_name="s3",
                operation_name="list_objects_v2",
                parameters={"Bucket": bucket_name, "Prefix": prefix},
                region=self.aws_region,
                label=f"List objects in S3 bucket {bucket_name} with prefix {prefix}"
            )
            
            logger.info(f"成功获取S3对象列表: {bucket_name}/{prefix}")
            
            # 检查返回结果的类型和内容
            content = result.get('content')
            if isinstance(content, list):
                # 如果内容是列表，进行深度遍历分析
                traversal_result = traverse_list_content(content)
                
                return {
                    "raw_result": result,
                    "content": content,
                    "content_type": type(content).__name__,
                    "traversal_result": traversal_result
                }
            else:
                # 如果内容不是列表，返回基本信息
                return {
                    "raw_result": result,
                    "content": content,
                    "content_type": type(content).__name__,
                    "message": "内容不是列表类型，无法使用traverse_list_content函数"
                }
                
        except Exception as e:
            logger.error(f"列出S3对象失败: {e}")
            raise
    
    def download_and_read_file(self, bucket_name: str, s3_key: str) -> Dict[str, Any]:
        """
        下载S3文件并使用Agent读取内容
        
        该方法执行以下步骤：
        1. 使用Agent调用S3 get_object API下载文件
        2. 检查下载结果的数据类型
        3. 如果是列表类型，进行遍历分析
        4. 返回结构化的分析结果
        
        Args:
            bucket_name (str): S3存储桶名称
            s3_key (str): S3对象键（文件路径）
            
        Returns:
            Dict[str, Any]: 包含以下字段的字典：
                - s3_key: 原始S3对象键
                - download_result: 下载操作的原始结果
                - content_type: 内容数据类型
                - traversal_result: 列表内容的遍历结果（如适用）
                - content: 直接内容（如果不是列表类型）
                
        Raises:
            Exception: 如果下载或读取过程中出现错误
        """
        try:
            # 使用Agent下载S3文件
            download_result = self.agent.tools.use_aws(
                service_name="s3",
                operation_name="get_object",
                parameters={"Bucket": bucket_name, "Key": s3_key},
                region=self.aws_region,
                label=f"Download file {s3_key} from S3 bucket {bucket_name}"
            )
            
            # 如果下载结果是列表，进行遍历分析
            if isinstance(download_result.get('content'), list):
                print(type(download_result['content']))  # 调试输出
                traversal_result = traverse_list_content(download_result['content'])
                
                return {
                    "s3_key": s3_key,
                    "download_result": download_result,
                    "content_type": type(download_result.get('content')).__name__,
                    "traversal_result": traversal_result
                }
            else:
                # 如果不是列表，直接返回内容
                return {
                    "s3_key": s3_key,
                    "download_result": download_result,
                    "content_type": type(download_result.get('content')).__name__,
                    "content": download_result.get('content')
                }
                
        except Exception as e:
            logger.error(f"下载和读取文件失败 {s3_key}: {e}")
            raise
    
    def cleanup(self):
        """
        清理临时文件和目录
        
        该方法负责清理在文件下载过程中创建的临时目录和文件，
        确保不会留下垃圾文件占用磁盘空间。
        """
        if self.temp_dir and os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
            logger.info(f"清理临时目录: {self.temp_dir}")
    
    def __enter__(self):
        """
        上下文管理器入口方法
        
        Returns:
            S3DownloadAgent: 返回自身实例，支持with语句
        """
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        上下文管理器退出方法，自动清理资源
        
        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常追踪信息
            
        Note:
            无论是否发生异常，都会执行清理操作
        """
        self.cleanup()

# ============================================================================
# AI模型配置部分
# ============================================================================

# 配置OpenAI兼容的模型，使用SiliconFlow作为API提供商
API_KEY = os.environ.get('API_KEY')
model = OpenAIModel(
    client_args={
        # API密钥 - 注意：在生产环境中应该使用环境变量存储
        "api_key": API_KEY,
        # 使用SiliconFlow的API端点，提供DeepSeek模型服务
        "base_url": "https://api.siliconflow.cn/v1"
    },
    # 使用DeepSeek-V3模型，适合中文文本分析
    model_id="deepseek-ai/DeepSeek-V3",
    params={
        "temperature": 0.7,    # 控制输出的随机性，0.7提供平衡的创造性
        "max_tokens": 8000,    # 最大输出token数，确保能生成完整的分析报告
    }
)

# ============================================================================
# 系统提示词配置部分
# ============================================================================

# 基础版本的系统提示词（已弃用，保留作为参考）
system_prompt="""
你是一个人力资源分析师，请执行以下步骤：
1. 提取基本信息（姓名、联系方式、工作经验年限）
2. 分析技能关键词和专业领域
3. 评估工作经验匹配度（按1-10分评分）
4. 提取教育背景
5. 识别突出亮点

最终，请生成一份综合汇总报告，包含：
- 按匹配度排序的推荐建议
- 这个候选人是否满足要求
"""

# 改进版本的系统提示词（当前使用）
# 该提示词设计了结构化的分析流程和标准化的JSON输出格式
system_prompt_improved="""
你是一个专业的人力资源分析师，负责评估求职候选人。

<任务>
分析候选人简历并生成标准化的JSON格式评估报告。
</任务>

<简历>
{{简历内容}}
</简历>

<分析步骤>
1. 提取基本信息（姓名、联系方式、工作经验年限）
2. 分析技能关键词和专业领域
3. 评估工作经验匹配度（按1-10分评分）
4. 提取教育背景
5. 识别突出亮点
</分析步骤>

<评估标准>
- 技能匹配度：候选人的技能与职位要求的匹配程度
- 经验相关性：候选人的工作经历与目标职位的相关程度
- 教育背景：候选人的学历是否满足职位要求
- 综合素质：根据简历整体表现评估候选人的综合能力
</评估标准>

<输出格式>
请以JSON格式输出分析结果，包含以下字段：
```json
{
  "name": "候选人姓名",
  "score": 数字(1-10),
  "综合评价": "详细的综合评价",
  "基本信息": {
    "联系方式": "电话/邮箱",
    "工作经验": "年限"
  },
  "技能分析": ["技能1", "技能2", "技能3"],
  "教育背景": "学历信息",
  "亮点": ["亮点1", "亮点2"],
  "推荐建议": "是否推荐及理由",
  "selected": true或false
}
```
</输出格式>

请确保JSON格式正确，所有字段均使用中文，并提供详细的综合评价。
"""

# 创建AI Agent实例，配置改进版的系统提示词和相关工具
agent = Agent(
    system_prompt=system_prompt_improved,  # 使用改进版的提示词
    model=model,                           # 使用上面配置的DeepSeek模型
    tools=[use_aws, file_read, swarm]      # 配置AWS操作、文件读取和协作工具
)

# ============================================================================
# 协作分析功能（当前存在问题，待修复）
# ============================================================================

# TODO：此函数存在错误，需要修复
def swarm_agent(resume_contents: str) -> str:
    """
    使用Swarm多代理协作分析简历内容
    
    该函数设计用于并发分析多份简历，通过多个AI Agent协作处理：
    1. 将简历内容分发给多个Agent
    2. 每个Agent专注分析特定的简历
    3. 所有Agent协作生成综合分析报告
    
    Args:
        resume_contents (str): 合并后的简历内容字符串
        
    Returns:
        str: 协作分析的结果报告
        
    Note:
        当前版本存在以下问题：
        - agent.tool.swarm 调用方式不正确（应该是 agent.tools.swarm）
        - 函数未被主流程调用
        - 需要测试和调试协作模式的参数配置
        
    设计理念：
        - 提高大批量简历处理的效率
        - 通过多Agent协作提供更全面的分析视角
        - 支持并发处理，减少总体处理时间
    """
    # 4. 将所有简历内容合并为一个任务描述
    combined_content = "\n\n".join(resume_contents)
    
    # 5. 使用 swarm 工具进行协作分析
    # 注意：这里存在bug，应该是 agent.tools.swarm 而不是 agent.tool.swarm
    result = agent.tool.swarm(
        model=model,
        task=f"""
            请分析以下简历内容，执行并发分析：
            
            {combined_content}
            
            每个 Agent 应该专注分析其中一份或几份简历，执行以下步骤：
            1. 提取基本信息（姓名、联系方式、工作经验年限）
            2. 分析技能关键词和专业领域
            3. 评估工作经验匹配度（按1-10分评分）
            4. 提取教育背景
            5. 识别突出亮点
            
            最终，请所有 Agent 协作生成一份综合汇总报告，包含：
            - 按匹配度排序的推荐建议
            - 每个候选人的优势和不足总结
            """,
            swarm_size=5,  # 限制最大5个Agent（原注释说10个，但参数是5）
            coordination_pattern="collaborative"     # 协作模式
    )
    
    # 6. 输出结果
    print("=== 简历分析汇总报告 ===")
    print(result["content"])

# ============================================================================
# 核心处理函数
# ============================================================================

def traverse_list_content(content: List[Any], max_depth: int = 3, current_depth: int = 0) -> Dict[str, Any]:
    """
    遍历和处理S3对象列表内容的核心函数
    
    这是整个系统的核心处理函数，负责：
    1. 解析S3 API返回的对象列表
    2. 下载每个简历文件
    3. 将文件转换为可分析的文本格式
    4. 使用AI Agent分析每份简历
    5. 输出分析结果
    
    处理流程：
    1. 遍历S3对象列表中的每个项目
    2. 解析JSON格式的文件信息
    3. 逐个下载S3中的简历文件
    4. 使用MarkItDown将文件转换为文本
    5. 调用AI Agent进行简历分析
    6. 输出候选人评估结果
    
    Args:
        content (List[Any]): S3 API返回的对象列表
        max_depth (int): 最大遍历深度，防止无限递归，默认为3
        current_depth (int): 当前遍历深度，用于递归控制
        
    Returns:
        Dict[str, Any]: 处理结果字典，包含统计信息和详细内容
        
    Note:
        该函数包含复杂的数据解析逻辑，需要处理以下格式转换：
        - S3 API响应 -> JSON字符串 -> Python对象
        - 各种文档格式 -> Markdown文本
        - 文本内容 -> AI分析结果
        
    异常处理：
        - 深度限制：防止无限递归
        - JSON解析错误：记录并跳过无效数据
        - 文件下载失败：记录错误但继续处理其他文件
        - AI分析失败：记录错误但不中断整个流程
    """
    # 检查递归深度限制，防止无限递归
    if current_depth >= max_depth:
        return {"error": "达到最大遍历深度", "depth": current_depth}
    
    result = []  # 存储处理结果
    
    try:
        resume_contents = []  # 存储简历内容（当前未使用，为future功能预留）
        
        # 遍历S3对象列表中的每个项目
        for index, item in enumerate(content, 1):
            # 数据清理和格式转换
            # 原始数据包含特殊字符和Python布尔值，需要转换为有效的JSON格式
            string_format = item["text"].replace("\"", "").replace("'", "\"").replace("False", "\"False\"").replace("True", "\"True\"")
            
            # 解析JSON字符串，提取文件列表信息
            # 注意：这里假设JSON字符串以特定格式开始，需要截取有效部分
            json_str = json.loads(string_format[8:len(string_format)]).get("Contents")
            
            # 处理每个文件
            for fileIndex, file in enumerate(json_str, 1):
                # 从S3下载文件到本地
                # 使用download_file操作而不是get_object，直接保存到本地文件系统
                result = agent.tool.use_aws(
                        service_name="s3",
                        operation_name="download_file",
                        parameters={
                            "Filename": file.get('Key'),    # 本地文件名
                            "Key": file.get('Key'),         # S3对象键
                            "Bucket": "cv-workshop-test"    # S3存储桶名称
                        },
                        region="cn-northwest-1",            # AWS区域
                        label="List all files in S3 buckets"
                )
                
                # 使用MarkItDown库将文档转换为Markdown格式
                # 支持多种文档格式：PDF, Word, Excel, PowerPoint等
                with open(file.get('Key'), "rb") as f:  
                    md = MarkItDown()  
                    result = md.convert_stream(f)  
                    # 可选：将简历内容添加到列表中，用于批量处理
                    #resume_contents.append(f"=== 简历 {file} (来源: {file}) ===\n{result.text_content}")
                
                # 使用AI Agent分析简历内容
                # 组合职位要求和简历内容，让AI进行匹配分析
                results = agent("我要找一个软件开发工程师，这个简历是否合适." + "简历内容：" + result.text_content)
                
                # 输出分析结果
                print("候选人的结果如下：")
                # 调试输出（已注释）
                #print("=========================================================")
                #print(results) 
                #print("=========================================================")
   
    except Exception as e:
        # 记录处理过程中的错误，但不中断整个流程
        logger.error(f"遍历列表内容时出错: {e}")
    
    return result


# ============================================================================
# 主程序入口
# ============================================================================

def main():
    """
    主函数 - 简历分析系统的程序入口点
    
    该函数执行完整的简历分析流程：
    1. 连接AWS S3服务
    2. 获取指定存储桶中的所有简历文件
    3. 逐个下载和分析简历
    4. 输出AI分析结果
    
    执行流程：
    1. 使用Agent调用S3 list_objects_v2 API获取文件列表
    2. 检查返回结果的数据类型
    3. 如果是列表类型，调用traverse_list_content进行深度处理
    4. traverse_list_content函数会：
       - 下载每个简历文件
       - 转换为文本格式
       - 使用AI进行分析
       - 输出评估结果
    
    配置信息：
    - S3存储桶：cv-workshop-test
    - AWS区域：cn-northwest-1（中国西北区域）
    - 目标职位：软件开发工程师
    
    Returns:
        int: 程序退出码
             0 - 成功执行
             1 - 执行过程中出现错误
             
    异常处理：
        捕获所有异常并记录错误信息，确保程序优雅退出
    """
    try:
        logger.info("开始执行简历分析流程...")
        
        # 步骤1：获取S3存储桶中的文件列表
        # 使用Agent的AWS工具调用S3 API
        result = agent.tool.use_aws(
            service_name="s3",                          # AWS服务名称
            operation_name="list_objects_v2",           # S3操作：列出对象（版本2）
            parameters={"Bucket": "cv-workshop-test"},  # 参数：指定存储桶名称
            region="cn-northwest-1",                    # AWS区域：中国西北区域
            label="List all files in S3 buckets"       # 操作描述标签
        )
        
        logger.info(f"成功获取S3文件列表，返回数据类型：{type(result.get('content'))}")
                
        # 步骤2：检查返回结果并进行深度处理
        # 如果内容是列表类型，说明成功获取到文件信息，进行进一步处理
        if isinstance(result['content'], list):
            print("\n" + "="*50)
            print("开始使用traverse_list_content函数进行深度分析:")
            print("="*50)
            
            # 调用核心处理函数，执行文件下载和AI分析
            traversal_result = traverse_list_content(result['content'])
            
            logger.info("简历分析流程完成")
        else:
            logger.warning(f"返回内容不是列表类型，无法进行批量处理。内容类型：{type(result.get('content'))}")
        
    except Exception as e:
        # 捕获并记录所有异常
        logger.error(f"程序执行失败: {e}")
        return 1
    
    logger.info("程序执行成功完成")
    return 0


# 程序入口点
# 当脚本直接运行时（而不是被导入时），执行main函数
if __name__ == "__main__":
    exit(main())