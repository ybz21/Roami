---
name: 主Agent本地图片输入
description: 保持保存的角色能力独立，使Main明确读取的本地图片以真实像素进入模型，并校验当前回执、文件边界和共享图片载荷。
---

`input/image.json`是公开Pillow合成配方，与实际Runtime测试夹具逐字节一致。使用真实保存接口和Main执行循环、SQLite及本地模型事件，不调用外部模型。测试不含原题视频帧或隐藏参考。
