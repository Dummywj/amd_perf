测试 AMD 服务器的长向量性能表现，主要是 softmax，fma，reduce，gather 等操作。
数据类型：FP32 和 BF16
数据结果：各类关键向量操作：elem/cycle（平均每周期处理的元素个数）

目前在 gbench-test 目录下完成各类测试。