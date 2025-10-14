/*
 * s10077_driver.h
 *
 *  Created on: Oct 14, 2025
 *      Author: 91281
 */

#ifndef INC_S10077_DRIVER_H_
#define INC_S10077_DRIVER_H_

#include "main.h" // For HAL types and configurations
#include <stdbool.h>


//================================================================================
// User-configurable Parameters
// (JP) ユーザーが設定可能なパラメータ
//================================================================================

// Total number of pixels for the S10077 sensor.
// (JP) S10077センサーの総ピクセル数。
#define S10077_NUM_PIXELS           1024

// Integration time in milliseconds. Adjust this value based on light intensity.
// (JP) 積分時間（ミリ秒）。光の強度に応じてこの値を調整してください。
#define S10077_INTEGRATION_TIME_MS  10


//================================================================================
// Public Function Prototypes
// (JP) 公開関数のプロトタイプ
//================================================================================

/**
 * @brief  Initializes the S10077 driver with necessary HAL handles.
 * This function MUST be called once before any other driver functions.
 * (JP) S10077ドライバを必要なHALハンドルで初期化します。
 * (JP) この関数は、他のドライバ関数を呼び出す前に一度だけ呼び出す必要があります。
 * @param  hadc: Pointer to the ADC handle. (JP) ADCハンドルへのポインタ。
 * @param  htim_clk: Pointer to the TIM handle generating the CLK signal. (JP) CLK信号を生成するTIMハンドルへのポインタ。
 * @param  st_port: GPIO port for the ST signal. (JP) ST信号用のGPIOポート。
 * @param  st_pin: GPIO pin for the ST signal. (JP) ST信号用のGPIOピン。
 * @retval None
 */
void S10077_Init(ADC_HandleTypeDef* hadc, TIM_HandleTypeDef* htim_clk, GPIO_TypeDef* st_port, uint16_t st_pin);

/**
 * @brief  Starts a single acquisition cycle. This is a non-blocking function.
 * (JP) 1回の取得サイクルを開始します。これはノンブロッキング関数です。
 * @retval None
 */
void S10077_StartAcquisition(void);

/**
 * @brief  Checks if the data acquisition is complete.
 * (JP) データ取得が完了したかどうかを確認します。
 * @retval true if data is ready, false otherwise. (JP) データが準備できていればtrue、そうでなければfalse。
 */
bool S10077_IsDataReady(void);

/**
 * @brief  Gets a pointer to the internal data buffer.
 * Call this only after S10077_IsDataReady() returns true.
 * (JP) 内部データバッファへのポインタを取得します。
 * (JP) S10077_IsDataReady()がtrueを返した後にのみ呼び出してください。
 * @retval Pointer to the 16-bit pixel data array. (JP) 16ビットのピクセルデータ配列へのポインタ。
 */
uint16_t* S10077_GetData(void);

/**
 * @brief  Gets the total number of pixels.
 * (JP) 総ピクセル数を取得します。
 * @retval Total number of pixels. (JP) 総ピクセル数。
 */
uint32_t S10077_GetNumPixels(void);

#endif /* INC_S10077_DRIVER_H_ */
