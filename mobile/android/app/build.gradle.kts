plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.roami.app"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.roami.app"
        minSdk = 26
        targetSdk = 34
        versionCode = 7
        versionName = "0.3.3"
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            // 自托管：部署者自己签。没配签名就用 debug 签，能装能用，只是不能上商店
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.2")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation("junit:junit:4.13.2")
}
