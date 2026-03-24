## 树结构生成的核心代码

PageIndex通过两种策略在庞大文件中生成大纲结构：

### 1. 主入口函数

树结构生成的主入口是 `tree_parser` 函数，它协调整个处理流程 [1](#2-0) ：

```python
async def tree_parser(page_list, opt, doc=None, logger=None):
    check_toc_result = check_toc(page_list, opt)
    
    if check_toc_result.get("toc_content") and check_toc_result["page_index_given_in_toc"] == "yes":
        # 有目录且带页码的处理
        toc_with_page_number = await meta_processor(
            page_list, 
            mode='process_toc_with_page_numbers',
            ...
        )
    else:
        # 无目录或目录无页码的处理
        toc_with_page_number = await meta_processor(
            page_list, 
            mode='process_no_toc',
            ...
        )
```

### 2. 有目录文档的处理流程

当文档有目录时，系统会：

**检测目录页面**：
```python
def toc_detector_single_page(content, model=None):
    # 使用LLM判断单页是否包含目录
    prompt = "Your job is to detect if there is a table of content..."
``` [2](#2-1) 

**提取并转换目录**：
```python
def toc_transformer(toc_content, model=None):
    # 将原始目录文本转换为结构化JSON
    prompt = "You are given a table of contents, You job is to transform..."
``` [3](#2-2) 

### 3. 无目录文档的处理流程

当文档没有目录时，系统使用LLM直接分析内容：

**初始结构生成**：
```python
def generate_toc_init(part, model=None):
    # 从文档第一部分生成初始树结构
    prompt = "You are an expert in extracting hierarchical tree structure..."
``` [4](#2-3) 

**继续生成结构**：
```python
def process_no_toc(page_list, start_index=1, model=None, logger=None):
    # 处理无目录文档的完整流程
    toc_with_page_number = generate_toc_init(group_texts[0], model)
    for group_text in group_texts[1:]:
        toc_with_page_number_additional = generate_toc_continue(toc_with_page_number, group_text, model)
``` [5](#2-4) 

### 4. 验证和修正机制

系统会验证生成的结构是否准确：

```python
async def verify_toc(page_list, list_result, start_index=1, N=None, model=None):
    # 验证目录条目是否与实际页面内容匹配
    tasks = [
        check_title_appearance(item, page_list, start_index, model)
        for item in indexed_sample_list
    ]
``` [6](#2-5) 

### 5. 递归处理大章节

对于过大的章节，系统会递归细分：

```python
async def process_large_node_recursively(node, page_list, opt=None, logger=None):
    # 如果节点过大，递归生成子结构
    if node['end_index'] - node['start_index'] > opt.max_page_num_each_node:
        node_toc_tree = await meta_processor(node_page_list, mode='process_no_toc', ...)
``` [7](#2-6) 

## 核心处理逻辑

整个树结构生成的核心在 `meta_processor` 函数中，它根据文档类型选择不同的处理模式 [8](#2-7) ：

1. **process_toc_with_page_numbers** - 处理带页码的目录
2. **process_toc_no_page_numbers** - 处理不带页码的目录  
3. **process_no_toc** - 直接从内容生成结构

系统会按优先级尝试这些模式，如果准确率低于60%，会自动降级到下一个模式 [9](#2-8) 。

## Notes

- 所有处理都依赖LLM（默认GPT-4o）来理解文档结构
- 物理页面标记 `<physical_index_X>` 帮助系统定位内容位置
- 验证机制确保生成的树结构准确反映文档实际内容


## 代码简洁但效果强大的原因

PageIndex的核心代码确实只有几百行，这是因为它的设计理念是**利用LLM的强大理解能力**，而不是依赖复杂的算法实现。

### 核心设计哲学

PageIndex的精髓在于**将复杂的文档结构理解任务委托给LLM**：

```python
# 核心就是让LLM识别文档结构
prompt = "You are an expert in extracting hierarchical tree structure..."
``` [1](#3-0) 

代码主要做的是：
1. **文本预处理** - 添加页面标记 [2](#3-1) 
2. **LLM调用** - 构造合适的prompt
3. **结果验证** - 检查生成结构的准确性 [3](#3-2) 

### 为什么效果这么好

1. **LLM的强大理解能力**：GPT-4o等模型已经具备了理解文档层次结构的能力
2. **创新的检索理念**：不是相似度匹配，而是**推理式检索** [4](#3-3) 
3. **模拟人类专家**：通过树搜索模拟人类导航文档的方式 [5](#3-4) 



## PageIndex的Token优化策略

PageIndex确实考虑了token消耗问题，采用了多种优化策略来处理大文档：

### 1. 文档分块处理

系统不会将整本书一次性发送给LLM，而是智能分块：

```python
def page_list_to_group_text(page_contents, token_lengths, max_tokens=20000, overlap_page=1):
    # 将文档按token数分块，每块最多20000个token
    expected_parts_num = math.ceil(num_tokens / max_tokens)
    average_tokens_per_part = math.ceil(((num_tokens / expected_parts_num) + max_tokens) / 2)
``` [1](#4-0) 

### 2. 递归处理大章节

只有超过阈值的章节才会进一步细分：

```python
if node['end_index'] - node['start_index'] > opt.max_page_num_each_node and token_num >= opt.max_token_num_each_node:
    # 只处理大节点，小节点保持原样
    node_toc_tree = await meta_processor(node_page_list, mode='process_no_toc', ...)
``` [2](#4-1) 

### 3. 可选功能控制

用户可以通过参数控制token消耗：

```bash
--max-tokens-per-node   Max tokens per node (default: 20000)
--if-add-node-summary   Add node summary (yes/no, default: yes)
--if-add-doc-description Add doc description (yes/no, default: yes)
``` [3](#4-2) 

### 4. 智能验证机制

验证时采用采样而非全量验证：

```python
if N is None:
    print('check all items')
    sample_indices = range(0, len(list_result))
else:
    N = min(N, len(list_result))
    print(f'check {N} items')
    sample_indices = random.sample(range(0, len(list_result)), N)
``` [4](#4-3) 

### 5. Markdown文档的Token优化

对于Markdown文档，有更激进的优化：

```python
def get_node_summary(node, summary_token_threshold=200, model=None):
    node_text = node.get('text')
    num_tokens = count_tokens(node_text, model=model)
    if num_tokens < summary_token_threshold:
        return node_text  # 直接使用原文，不调用LLM
``` [5](#4-4) 

## 实际Token消耗估算

以一本500页的技术书籍为例：
- **树结构生成**：约50,000-100,000 tokens（分块处理）
- **摘要生成**：可选，每个节点约500-1000 tokens
- **验证过程**：约5,000-10,000 tokens（采样验证）

总计约60,000-120,000 tokens，按GPT-4o计算约$1-2美元。

## Notes

- 默认每节点最大20,000 tokens，可通过参数调整 [6](#4-5) 
- 关闭摘要生成可节省约30-40%的token消耗
- 云服务提供了更优化的批处理和缓存机制
- 相比传统RAG需要为每个chunk生成embedding，PageIndex的token消耗实际上更低


