#include <stdio.h>

// Simulated actuator / motor control module

void control_actuator(int command) {
    switch (command) {
        case 0:
            printf("  [ACT] Shutdown.\n");
            break;
        case 1:
            printf("  [ACT] Cooling fan ON.\n");
            break;
        case 2:
            printf("  [ACT] Normal operation.\n");
            break;
        case 3:
            printf("  [ACT] Heater ON.\n");
            break;
        default:
            printf("  [ACT] Unknown command.\n");
            break;
    }
}

void run_actuator_self_test(void) {
    for (int i = 0; i < 4; i++) {
        control_actuator(i);
    }
}
