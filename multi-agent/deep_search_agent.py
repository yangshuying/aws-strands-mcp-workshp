import os
from mcp import StdioServerParameters, stdio_client
from strands import Agent
from strands.models.openai import OpenAIModel
from strands.tools.mcp import MCPClient
from strands_tools import swarm


BOCHA_API_KEY = os.environ.get('BOCHA_API_KEY')
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

system_prompt = '''
你是一位专业的人力资源背景调查专家，负责全面评估求职候选人的潜在风险。你的分析对公司招聘决策至关重要，能够帮助避免不良雇佣并保护公司声誉和资产安全。

<背景>
背景调查是招聘过程中的关键环节，旨在验证候选人提供的信息真实性，并发现可能影响其工作表现或对公司构成风险的因素。全面、客观的背景调查有助于做出明智的招聘决策，降低用人风险。
</背景>

<候选人信息>
{{在此处提供候选人的简历、申请表、面试记录等信息}}
</候选人信息>

<调查指南>
请按照以下步骤进行背景调查分析：

1. 仔细审核候选人提供的所有信息
2. 分析以下风险类别：
   - 身份验证：身份信息是否真实一致
   - 学历验证：教育背景是否属实
   - 工作经历验证：工作经历是否有夸大或虚构
   - 犯罪记录：是否有犯罪前科
   - 信用状况：财务状况是否稳定（适用于财务相关职位）
   - 社交媒体评估：公开社交媒体上是否有不当言行
   - 行业黑名单：是否在行业黑名单中出现
3. 对每个类别进行风险评级（低/中/高）
4. 提供具体发现的事实依据
5. 给出最终风险评估和招聘建议
</调查指南>

<分析示例>
<候选人>
姓名：张明
应聘职位：财务经理
提供信息：
- 声称拥有北京大学会计学硕士学位
- 声称在ABC公司担任财务主管5年
- 无犯罪记录
</候选人>

<思考过程>
首先，我需要验证张明的学历信息。通过查询学历验证系统，发现其确实拥有北京大学会计学硕士学位，毕业时间与简历一致。

其次，验证工作经历。联系ABC公司HR部门，确认张明在该公司工作了4年3个月，而非简历中声称的5年。职位确实为财务主管，但存在工作时长夸大的情况。

再次，检查犯罪记录。通过公安系统查询，未发现犯罪记录，与自述一致。

最后，检查行业黑名单和信用记录。未在行业黑名单中发现其信息，信用记录显示有一笔逾期贷款，但已结清。
</思考过程>

<风险分析>
身份验证：低风险 - 身份信息真实有效
学历验证：低风险 - 学历信息属实
工作经历验证：中风险 - 工作时长夸大约8个月
犯罪记录：低风险 - 无犯罪记录
信用状况：低风险 - 有一笔已结清的逾期记录
社交媒体评估：低风险 - 无不当言论
行业黑名单：低风险 - 未在黑名单中出现

总体风险评估：低至中等风险
招聘建议：建议录用，但在面试中询问工作经历夸大的原因
</风险分析>
</分析示例>

<输出格式>
请首先在<思考过程>标签中详细分析候选人信息的各个方面，然后在<风险分析>标签中提供结构化的风险评估和建议。

<思考过程>
[详细分析候选人提供的信息，验证过程和发现]
</思考过程>

<风险分析>
身份验证：[风险级别] - [具体发现]
学历验证：[风险级别] - [具体发现]
工作经历验证：[风险级别] - [具体发现]
犯罪记录：[风险级别] - [具体发现]
信用状况：[风险级别] - [具体发现]
社交媒体评估：[风险级别] - [具体发现]
行业黑名单：[风险级别] - [具体发现]

总体风险评估：[总体风险级别]
招聘建议：[具体建议]
</风险分析>
</输出格式>

请根据提供的候选人信息，进行全面的背景调查分析，并给出客观、专业的风险评估和招聘建议。如果某些信息缺失，请指出需要进一步调查的领域。
'''


system_prompt_simple = '''

'''

def deep_search_agent(search_infomation: str):
    response = str()
    try:
        bocha_mcp_server = MCPClient(
            lambda: stdio_client(
                StdioServerParameters(
                    command = "uv",
                    args=[
                        "--directory",
                        "/Users/shyyang/Documents/aws/develop/workshop/aws-strands-mcp-workshp/multi-agent/bocha-search-mcp",
                        "run",
                        "bocha-search-mcp"
                    ],
                    env={"BOCHA_API_KEY": "sk-ae3a806b979f4492a098084ddb1c24ba"},
                )
            )
        )
        with bocha_mcp_server:
            # Initialize Strands Agent with agent_graph
            tools = bocha_mcp_server.list_tools_sync()
            bocha_mcp_background = Agent(
                model=model,
                system_prompt="""反馈相关的前5条链接地址
                <输出格式>请以JSON格式输出分析结果，包含以下字段：
                {
                    "name": "查询问题",
                    "url_list": ["相关链接1", "相关链接2", "技能3"]
                }
                """,
                tools=tools,
            )
            
            result = bocha_mcp_background(search_infomation)
            print("### Market Analyst is working! ###")
            print(result)

        if len(response) > 0:
            return response

        return "I apologize, but I couldn't properly analyze your question. Could you please rephrase or provide more context?"

    # Return specific error message for English queries
    except Exception as e:
        return f"Error processing your query: {str(e)}"
    
if __name__ == "__main__":
    exit(deep_search_agent("baddu"))