# 书院导读中引文、转述与反驳的朗读编审

书院导读工作簿保存录文、释义、馆员校记、朗读原稿及馆内播控路径。所有人名、编号和业务记录都是合成数据。

使用 Python 3.11 和标准库，资料文件采用 UTF-8。业务资料的格式记录在 [资料说明](资料说明.md)。

## 资料检查

运行资料检查会读入记录、核对字段并显示各集合的条数。也可在后面指定单独的集合名。

```sh
python3 read_materials.py
python3 -m unittest discover -s tests -v
```

## 编审工具 `jiangtang`

`jiangtang` 包在资料检查之上提供可继续编新站点的编审能力。交入资料（`data/`）只读，
工具产生的判词、批准与交付写到独立工作目录 `work/`，两者互不覆盖。

```sh
# 建议以隔离模式运行，避免当前目录里的同名模块被误导入
python3 -I jiangtang_cli.py check                 # 字段与引用核对
python3 -I jiangtang_cli.py classify [稿片号]      # 字句性质初判与编辑判词
python3 -I jiangtang_cli.py disputes              # 释义分歧与挂靠稿片
python3 -I jiangtang_cli.py routes [路径号]        # 逐条校验开放收听路径
python3 -I jiangtang_cli.py shorten r1 --drop g0 g1   # 试算短听走法
python3 -I jiangtang_cli.py impact g3             # 反查稿片影响面
python3 -I jiangtang_cli.py adjudicate ...        # 按出处回点改判角色或性质
python3 -I jiangtang_cli.py approve r1 ...        # 批准单条收听路径
python3 -I jiangtang_cli.py deliver r1 [--strict] # 生成播控自洽交付并留档
python3 -I jiangtang_cli.py status                # 批准状态与被更正存查的旧录文
```

首次使用可运行 `python3 -I scripts/seed_workspace.py`，把已有签字 h1/h2/h3
落成结构化判词与批准；脚本可重复执行。

### 规则落点

1. **字句分级**：稿片按标点切成 span，自动区分 `quote`（逐字引用）、`paraphrase`
   （概述/现代重述）、`question`（反问）、`opponent`（转述对手的待反驳主张）、
   `narrator`（讲解员串词）。自动结果只是候选；只有`录文`能支撑逐字引文，
   拿`释义`回点逐字引文会被直接拒绝。
2. **角色不混口**：`有人说……` 这类对手主张标为 `opponent` 并把说话人记为转述对象，
   不会交给先生角色念，避免观众把他反对的意思当成他的教诲。
3. **争议不合并**：同一文献下两种释义（如 e2/e3）列为分歧并挂到相关稿片，
   交编辑逐片裁决，工具不会把两个解释揉成同一位古人的话。
4. **相邻两轮指代**：路径校验只回看当前片与前一片，代词找不到前文即报缺口；
   短听去掉铺垫后，只能用路径 `allowed_bridge` 内的串词补前提，串词必须插在
   代词出现之前，补后仍超预算则不可播。逐字引文内部的代词与凝固文言短语
   （如“待闻其事”）不按路径指代处理。
5. **反驳对象**：反问与“却/不足/勿”等反驳 span 必须在前两轮有主张可指；
   整条路径的开场设问不要求前文。
6. **影响面与重审**：批准按 span 锁定稿本号。改一片的说话人或断言范围后，
   `impact` 列出所有要重审的路径，批准状态转为“待重审”；未引用该片的路径
   无影响，保持可播。
7. **深度材料不串台**：短听只能删本路径正片，不能把观众未选择的稿片挪进来凑时长。
8. **版本隔离**：校记（e5）到生效日后，同文献同页旧录文（e1）转为存查；
   新交付若仍把旧录文当逐字出处会被拦截。历史交付按日期序号留档在
   `work/deliveries/`，仅供内部核对当年录过什么，前台不会把旧归因混进新交付。
9. **一次交付自洽**：`deliver` 产出的每条稿片都含角色、可朗读正文、线索页与
   逐条出处提示（含当前/存查状态）；`--strict` 下未批准有效的路径拒绝交付。

### 测试

```sh
python3 -I -m unittest discover -s tests -v
```
