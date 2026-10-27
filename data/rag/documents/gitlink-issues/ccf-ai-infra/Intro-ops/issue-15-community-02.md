---
source_type: gitlink_issue
trust_level: community
source_url: https://www.gitlink.org.cn/ccf-ai-infra/Intro-ops/issues/15
source_updated_at: "2026-05-21 13:09"
repository: ccf-ai-infra/Intro-ops
issue_index: "15"
answer_author: CFHaini
---
# 遇到的cmake构建问题（已解决）

**环境**：我租用的 曦云 C500 服务器，镜像为TileLang 0.1.5，conda 环境为base
**流程**：<br>
1. 首先克隆仓库
2. 在Intro-ops文件夹下使用 
```bash
bash scripts/build_metax.sh env
```
之后运行
```bash
bash scripts/build_metax.sh configure
```
在这里会报错 
```python
/opt/conda/bin/python3: No module named cmake.__main__; 'cmake' is a package and cannot be directly executed
```
我的解决方法是
```bash
pip install cmake
```
这样就可以不用修改build_metax.sh中的内容，就可以进行构建，不知道有没有更好的方法，还是我的流程不对？
之后就是正常的构建和测试：
```bash
bash scripts/build_metax.sh build
bash scripts/build_metax.sh test
```

构建完成进行测试会发现全部通过，然后我去看了ops文件夹下，发现metax后端已经写好了
