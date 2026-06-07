#include <stdio.h>
#include <stdbool.h>

#define SENSOR_PIN      0x01
#define MAX_TEMP        100
#define CRITICAL_TEMP   120

volatile int system_state = 0;

int read_sensor(int channel);
void control_actuator(int command);
void run_actuator_self_test(void);
int check_sensor_status(int value);

int main(void) {
    int current_temp = 0;
    int loop_counter = 0;

    // Run self-test first
    run_actuator_self_test();

    while (loop_counter < 5) {

        current_temp = read_sensor(SENSOR_PIN);
        int sensor_ok = check_sensor_status(current_temp);

        if (current_temp >= CRITICAL_TEMP) {
            system_state = 2;
            control_actuator(0);
        } else if (current_temp >= MAX_TEMP && current_temp < CRITICAL_TEMP) {
            system_state = 1;
            control_actuator(1);
        } else if (current_temp > 25) {
            system_state = 0;
            control_actuator(2);
        } else {
            if (current_temp < 0) {
                control_actuator(3);
            } else {
                control_actuator(4);
            }
        }

        switch (system_state) {
            case 0:
                printf("[State 0] Normal. Temp: %d C\n", current_temp);
                break;
            case 1:
                printf("[State 1] Warning. Temp: %d C\n", current_temp);
                break;
            case 2:
                printf("[State 2] CRITICAL FAULT.\n");
                switch (current_temp) {
                    case 120:
                        printf("Fault: Exact thermal limit.\n");
                        break;
                    default:
                        printf("Fault: Severe overheating.\n");
                        break;
                }
                break;
            default:
                printf("Unknown state.\n");
                break;
        }

        loop_counter++;
    }

    return 0;
}
