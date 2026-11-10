# 代码来源

- 公开仓库：https://github.com/globocom/m3u8
- 固定提交：bfbfd48fccf446471dde0731f68f23d6c8299301
- 提交页：https://github.com/globocom/m3u8/commit/bfbfd48fccf446471dde0731f68f23d6c8299301
- 版本：setup.py 声明 6.0.0。
- 许可：MIT，原件 LICENSE 和源码版权声明原样保留。
- 取得方式：2026-11-10 从上述公开仓库 git clone --depth 1，核对 HEAD 与 GitHub 提交 API 返回的完整 SHA 相同；随后 fetch --unshallow 补齐上游历史，HEAD 保持不变。origin 保留上游地址。

初始材料没有修改 m3u8/、tests/ 或其他上游实现。新增 prompt.txt、运行说明.md、UPSTREAM.md 和 task/；.gitignore 增补环境、缓存及凭据排除项。task 中的播放列表、验收检查、依赖锁定和跨平台基线运行器均为本题新增，播放列表是合成协议样本，不代表真实频道或媒体内容。新增接口尚未实现。

原始基线与运行前提见运行说明.md。本题快照提交与此上游提交分开记录，不把本题新增材料作为上游功能。
