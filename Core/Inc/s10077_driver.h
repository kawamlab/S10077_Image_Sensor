#ifndef INC_S10077_DRIVER_H_
#define INC_S10077_DRIVER_H_

#include "main.h"
#include <stdbool.h>

//================================================================================
// User-configurable Parameters
//================================================================================
#define S10077_NUM_PIXELS           1024
#define S10077_INTEGRATION_TIME_MS  10

//================================================================================
// Sensor Configuration Structure
//================================================================================
/**
 * @brief  Structure to hold all hardware-specific handles for a single sensor.
 * An array of these structures will be defined in main.c to describe the system.
 */
typedef struct {
    ADC_HandleTypeDef* adc_handle;         // Pointer to the ADC peripheral (e.g., &hadc1)
    uint32_t           adc_channel;        // ADC channel for this sensor's AO (e.g., ADC_CHANNEL_1)

    TIM_HandleTypeDef* trig_tim_handle;    // Pointer to the TIM peripheral used for TRIG (e.g., &htim3)
    uint32_t           tim_trig_source;    // The specific TIM trigger source for TRIG (e.g., TIM_TS_TI1FP1 for CH1)

    GPIO_TypeDef* st_port;            // GPIO port for the ST signal (e.g., ST1_GPIO_Port)
    uint16_t           st_pin;             // GPIO pin for the ST signal (e.g., ST1_Pin)
} S10077_SensorConfig;

//================================================================================
// Public Function Prototypes
//================================================================================

/**
 * @brief  Initializes the S10077 driver system.
 * @param  configs: Pointer to an array of S10077_SensorConfig structures.
 * @param  num_sensors: The total number of sensors defined in the configs array.
 * @param  htim_clk: Pointer to the TIM handle generating the shared CLK signal.
 * @param  huart: Pointer to the UART handle for data transmission.
 */
void S10077_System_Init(const S10077_SensorConfig* configs, uint8_t num_sensors, TIM_HandleTypeDef* htim_clk, UART_HandleTypeDef* huart);

/**
 * @brief  Starts a single acquisition cycle for a specific sensor. This is non-blocking.
 * @param  sensor_id: The index of the sensor to acquire from (0 to num_sensors - 1).
 */
void S10077_StartAcquisition(uint8_t sensor_id);

/**
 * @brief  Checks if the data acquisition is complete.
 * @retval true if data is ready, false otherwise.
 */
bool S10077_IsDataReady(void);

/**
 * @brief  Transmits the acquired data of the last-read sensor over UART.
 * Format: "BEGIN,SENSOR_[ID],{data...},END\r\n"
 */
void S10077_PrintDataViaUART(void);

#endif /* INC_S10077_DRIVER_H_ */
