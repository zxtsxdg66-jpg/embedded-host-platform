# android

PC 网关的移动客户端：实时读数、统计与报警、环境问答、历史读数。不直连设备。

```bash
./gradlew assembleDebug          # 产物：app/build/outputs/apk/debug/app-debug.apk
./gradlew testDebugUnitTest      # JVM 单元测试，不需要模拟器；工程路径须为纯英文
```

页面、结构、构建限制与网关接口见 [`docs/android.md`](../docs/android.md)。
