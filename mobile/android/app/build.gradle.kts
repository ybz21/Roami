plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val releaseKeystore = System.getenv("ROAMI_ANDROID_KEYSTORE")

android {
    namespace = "com.roami.app"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.roami.app"
        minSdk = 26
        targetSdk = 34
        versionCode = 13
        versionName = "0.3.9"
    }
    signingConfigs {
        if (!releaseKeystore.isNullOrBlank()) {
            create("distribution") {
                storeFile = file(releaseKeystore)
                storePassword = System.getenv("ROAMI_ANDROID_STORE_PASSWORD")
                keyAlias = System.getenv("ROAMI_ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ROAMI_ANDROID_KEY_PASSWORD")
            }
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            // 本地自托管仍可用 debug 签名；公开发布由构建脚本强制要求固定证书。
            signingConfig = signingConfigs.getByName(if (releaseKeystore.isNullOrBlank()) "debug" else "distribution")
        }
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.2")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
