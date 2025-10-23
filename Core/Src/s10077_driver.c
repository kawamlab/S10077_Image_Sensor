#include "s10077_driver.h"
#include <stdio.h>
#include <string.h>

//================================================================================
// Private Variables
//================================================================================
static TIM_HandleTypeDef* clk_tim_handle;
static UART_HandleTypeDef* uart_handle;
static const S10077_SensorConfig* sensor_configs;
static uint8_t configured_sensor_count = 0;

static uint16_t adc_buffer[S10077_NUM_PIXELS];
static volatile bool data_ready_flag = false;
static uint8_t current_sensor_id = 0;
static ADC_HandleTypeDef* current_adc_handle = NULL; // Remember the currently active ADC handle
static TIM_HandleTypeDef* current_tim_handle = NULL; // Remember the currently active TIM handle

//================================================================================
// Public Function Implementations
//================================================================================

void S10077_System_Init(const S10077_SensorConfig* configs, uint8_t num_sensors, TIM_HandleTypeDef* htim_clk, UART_HandleTypeDef* huart)
{
    sensor_configs = configs;
    configured_sensor_count = num_sensors;
    clk_tim_handle = htim_clk;
    uart_handle = huart;

    if (HAL_TIM_PWM_Start(clk_tim_handle, TIM_CHANNEL_1) != HAL_OK)
    {
        Error_Handler();
    }
}

void S10077_StartAcquisition(uint8_t sensor_id)
{
    if (sensor_id >= configured_sensor_count) {
        return; // Invalid sensor ID
    }

    current_sensor_id = sensor_id;
    const S10077_SensorConfig* config = &sensor_configs[sensor_id];
    // Store the handle of the ADC we are about to use. This is crucial for the callback.
    current_adc_handle = config->adc_handle;
    current_tim_handle = config->trig_tim_handle;
    data_ready_flag = false;

    // --- Dynamically Reconfigure ADC ---
	// ADC should be stopped (ADEN=0) by HAL_ADC_Stop_DMA in the callback

	// Step 1: Configure ADC Channel (Modify SQRx register)
	ADC_ChannelConfTypeDef sConfig = {0};
	sConfig.Channel = config->adc_channel;
	sConfig.Rank = 1;
	sConfig.SamplingTime = ADC_SAMPLETIME_28CYCLES; // Make sure this sampling time is sufficient
	if (HAL_ADC_ConfigChannel(current_adc_handle, &sConfig) != HAL_OK)
	{
		Error_Handler();
	}

	// Step 2: Configure ADC Trigger Source (Modify EXTSEL register)
#if defined(STM32F446xx)
	MODIFY_REG(current_adc_handle->Instance->CR2, ADC_CR2_EXTSEL, config->adc_extsel_trigger);
#elif defined(STM32H723xx)
	MODIFY_REG(current_adc_handle->Instance->CFGR, ADC_CFGR_EXTSEL, config->adc_extsel_trigger);
#else
	#error "Unsupported MCU type for dynamic EXTSEL switching."
#endif

    // Step 3: Prepare the correct ADC and DMA to listen for triggers from its pre-configured timer.
    // This is the ONLY activation command needed for the acquisition chain.
	if (HAL_ADC_Start_DMA(current_adc_handle, (uint32_t*)adc_buffer, S10077_NUM_PIXELS) != HAL_OK)
	{
		Error_Handler();
	}

    // Step 2: Send the ST pulse to the specific sensor to start its data readout.
    HAL_GPIO_WritePin(config->st_port, config->st_pin, GPIO_PIN_SET);
    HAL_Delay(S10077_INTEGRATION_TIME_MS);
    HAL_GPIO_WritePin(config->st_port, config->st_pin, GPIO_PIN_RESET);
}

bool S10077_IsDataReady(void)
{
    return data_ready_flag;
}

void S10077_PrintDataViaUART(void)
{
	if (!data_ready_flag) return;
	static char buf[S10077_NUM_PIXELS * 6 + 100];
    int n = 0;

    n += snprintf(buf + n, sizeof(buf) - n, "BEGIN,SENSOR_%u,", current_sensor_id);
    for (int i = 0; i < S10077_NUM_PIXELS; ++i) {
    	if (n >= (sizeof(buf) - 10)) {
    	            break;
		}
		n += snprintf(buf + n, sizeof(buf) - n, "%u,", adc_buffer[i]);
    }
    if (n < (sizeof(buf) - 6)) {
             n += snprintf(buf + n, sizeof(buf) - n, "END\r\n");
	}

    HAL_UART_Transmit(uart_handle, (uint8_t*)buf, n, HAL_MAX_DELAY);
}

//================================================================================
// HAL Callback Function Override
//================================================================================

void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef* hadc)
{
  // Check if this callback is from the ADC we expect
  if(current_adc_handle != NULL && hadc->Instance == current_adc_handle->Instance)
  {
    // Stop ADC. This will set ADEN=0 (H7) or ADON=0 (F4),
    // allowing safe reconfiguration in the next StartAcquisition().
    // This is necessary for H7 compatibility.
    HAL_ADC_Stop_DMA(current_adc_handle);

    // In Reset Mode, we don't need to stop the TIM manually.

    data_ready_flag = true;
  }
}
