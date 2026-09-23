plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.example.envmonitor"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.example.envmonitor"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.2-phase2"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.4")

    // 网络：只用 OkHttp。它同时提供 REST（普通 HTTP 请求）与 WebSocket 两种能力，
    // 因此不额外引入 Retrofit；JSON 解析用 Android 内置的 org.json，不引入
    // Gson/Moshi —— 第一阶段接口只有几个字段，依赖越少，版本冲突的风险越小。
    //
    // **2026-09-17 订正**：括号里原写"本项目开发环境无法编译验证 Android 工程"，
    // 已不属实（见 build.gradle.kts 顶部）。"少引入依赖"这条取向本身保留，但理由改为
    // 它真正成立的那个：每加一个依赖就多一次下载与版本解析，而演示前的构建不该冒
    // 这种险；且离线环境下拿不到未缓存的新依赖。
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    // JVM 单元测试：MessageParser 刻意不依赖任何 Android API，因此可以在普通 JVM 上
    // 直接测试解析逻辑（不需要模拟器/真机）。org.json 在 Android 上是系统自带的，
    // 但 JVM 单元测试环境里没有，所以这里补一个同 API 的实现给测试用。
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
