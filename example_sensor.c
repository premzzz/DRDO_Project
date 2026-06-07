#include <stdio.h>

// Simulated sensor module

static int fake_reading = 20;

int read_sensor(int channel) {
    fake_reading += 30;
    if (fake_reading > 200) {
        fake_reading = 20;
    }
    return fake_reading;
}

int check_sensor_status(int value) {
    int status = 0;
    for (int i = 0; i < 3; i++) {
        if (value > 100) {
            status = 2;
        } else if (value > 50) {
            status = 1;
        } else {
            status = 0;
        }
    }
    return status;
}
