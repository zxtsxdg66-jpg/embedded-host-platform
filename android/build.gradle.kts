// Top-level build file.
//
// 版本说明：以下 Android Gradle Plugin / Kotlin 版本组合是编写时选定的稳定搭配。
//
// **2026-09-17 订正**：此处原写"本项目的开发环境没有 Android SDK/Gradle，无法实际编译验证"，
// 已不属实，也与 gradle.properties 里 2026-08-15 的实测记录自相矛盾。本机确实有 SDK
// （local.properties 的 sdk.dir）与 Gradle wrapper，这套组合
// （AGP 8.5.2 + Kotlin 1.9.24 + Gradle 8.7 + JDK 17）已实跑通过：
// assembleDebug 成功、testDebugUnitTest 40 项全过（后者须在纯英文路径下跑，
// 原因见 gradle.properties）。这条过时的说明此前被当作"少引入依赖"的理由引用过，
// 留着会让人据一个假前提做决定，因此订正而不是删除。
plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
}
