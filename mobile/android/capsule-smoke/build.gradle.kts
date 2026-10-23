plugins {
    id("com.android.application")
}

android {
    namespace = "com.roami.capsulesmoke"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.roami.capsulesmoke"
        minSdk = 36
        targetSdk = 36
        versionCode = 2
        versionName = "0.2"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
