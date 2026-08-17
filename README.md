# WiFi Band Analyzer

A 100% software-based Wi-Fi band analysis and root-cause diagnosis platform.

---

## 1. Project Overview

WiFi Band Analyzer is a software-based solution designed to analyze Wi-Fi network performance and identify the likely root cause of performance degradation.

Instead of relying on physical enterprise routers, the project uses a virtualized Wi-Fi environment, software-based packet and telemetry analysis, mathematical RF models, and an interactive dashboard.

The system aims to go beyond simply displaying Wi-Fi metrics by analyzing the available information and classifying the likely cause of poor performance.

---

## 2. Problem Statement

When Wi-Fi performance is poor, users can usually observe symptoms such as:

- Low network speed
- Weak signal
- Unstable connection
- High packet loss
- Low link rate

However, basic Wi-Fi monitoring generally provides metrics without clearly explaining the underlying cause.

The performance degradation may be related to:

- Device hardware limitations
- Wi-Fi band or standard limitations
- Large distance between the client and access point
- Signal attenuation
- Interference or congestion
- Difference between theoretical and actual link performance

The goal of WiFi Band Analyzer is to analyze these factors and provide an explainable diagnosis.

---

## 3. Proposed Solution

The proposed system is a completely software-based Wi-Fi analysis platform.

The overall approach is:

Virtual Wi-Fi Environment  
↓  
Telemetry and Packet Capture  
↓  
Client Capability Parsing  
↓  
RF and Mathematical Analysis  
↓  
Diagnostic Engine  
↓  
Database / Fallback  
↓  
Interactive Dashboard

The system will simulate controlled Wi-Fi conditions and analyze the resulting data to determine the likely cause of performance degradation.

---

## 4. Project Objectives

The main objectives of the project are:

- Create a software-based Wi-Fi environment for controlled testing.
- Capture and analyze Wi-Fi telemetry.
- Identify client device capabilities.
- Analyze supported and active Wi-Fi bands.
- Evaluate RSSI, SNR, PHY rate, retry rate and packet loss.
- Apply mathematical RF/path-loss models.
- Classify the likely cause of performance degradation.
- Provide explainable diagnostic results.
- Provide fallback device information when packet-level information is unavailable.
- Display the analysis through an interactive dashboard.
- Validate the diagnostic system using controlled test scenarios.

---

## 5. System Architecture

The overall system consists of the following layers:

```text
┌──────────────────────────────────┐
│      Virtual Wi-Fi Environment   │
│   Virtual APs + Virtual Clients  │
└────────────────┬─────────────────┘
                 ↓
┌──────────────────────────────────┐
│    Telemetry / Packet Capture    │
│ RSSI | SNR | PHY | Retry | Loss  │
└────────────────┬─────────────────┘
                 ↓
┌──────────────────────────────────┐
│     Client Capability Parser     │
│ Bands | Channel Width | Standard │
└────────────────┬─────────────────┘
                 ↓
┌──────────────────────────────────┐
│       RF Analysis Engine         │
│ Distance | Path Loss | Attenuation│
└────────────────┬─────────────────┘
                 ↓
┌──────────────────────────────────┐
│       Diagnostic Engine          │
│ Hardware | Distance | Attenuation│
│ Congestion | Optimal             │
└────────────────┬─────────────────┘
                 ↓
┌──────────────────────────────────┐
│       Database / Fallback        │
└────────────────┬─────────────────┘
                 ↓
┌──────────────────────────────────┐
│       Interactive Dashboard      │
└──────────────────────────────────┘
