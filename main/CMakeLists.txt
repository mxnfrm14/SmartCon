idf_component_register(SRCS "app_hf_msg_set.c"
                            "audio_serial.c"
                            "phone_manager.c"
                            "pairing_security.c"
                            "bt_app_media.c"
                            "bt_app_core.c"
                            "bt_app_hf.c"
                            "gpio_pcm_config.c"
                            "bt_app_pbac.c"
                            "main.c"
                    PRIV_REQUIRES esp_timer bt nvs_flash esp_driver_gpio esp_driver_uart console esp_ringbuf
                    INCLUDE_DIRS ".")

target_link_libraries(${COMPONENT_LIB} INTERFACE
    "-Wl,--wrap=bta_dm_co_io_req" "-Wl,--wrap=BTA_DmConfirm")
