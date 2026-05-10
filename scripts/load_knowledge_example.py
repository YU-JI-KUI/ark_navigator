"""加载知识库示例"""

import httpx
import asyncio


async def load_knowledge_from_file(file_path: str, api_url: str = "http://localhost:8000"):
    """从文件加载知识库"""
    import json

    # 读取知识库文件
    with open(file_path, 'r', encoding='utf-8') as f:
        knowledge_data = json.load(f)

    # 发送到API
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{api_url}/api/v1/knowledge/load",
            json={"knowledge": knowledge_data}
        )
    result = response.json()
    print(f"加载结果: {result}")
    return result


async def load_knowledge_direct(knowledge_list: list, api_url: str = "http://localhost:8000"):
    """直接加载知识列表"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{api_url}/api/v1/knowledge/load",
            json={"knowledge": knowledge_list}
        )
    result = response.json()
    print(f"加载结果: {result}")
    return result


async def get_knowledge_stats(api_url: str = "http://localhost:8000"):
    """获取知识库统计"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{api_url}/api/v1/knowledge/stats")
    stats = response.json()
    print(f"知识库统计: {stats}")
    return stats


async def main():
    """示例, 加载知识"""

    # 示例1: 直接加载知识
    knowledge = [
        {"question": "什么是定期寿险", "answer": "定期寿险是在保险期间内，被保险人身故后，保险公司按约定支付保险金的保险产品。"},
        {"question": "终身寿险的特点", "answer": "终身寿险保障至被保人终身，兼具保障和储蓄功能，保费较高但保障终身。"},
        {"question": "两全保险是什么", "answer": "两全保险又称生死合险，无论被保险人在保险期间内身故还是期满再生存，都能获得保险金。"},
    ]

    print("=" * 60)
    print("加载知识到向量库")
    print("=" * 60)

    await load_knowledge_direct(knowledge)

    # 查看统计
    print("\n" + "=" * 60)
    print("查看知识库统计")
    print("=" * 60)

    await get_knowledge_stats()

    # 测试检索
    print("\n" + "=" * 60)
    print("测试知识检索")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/v1/knowledge/search",
            json={"query": "什么是寿险", "top_k": 3}
        )
    results = response.json()
    print(f"检索结果: {results['total']}条")
    for item in results['results']:
        print(f"  Q: {item['question']}")
        print(f"  A: {item['answer']}")
        print(f"  Score: {item['score']:.4f}\n")


if __name__ == "__main__":
    asyncio.run(main())
