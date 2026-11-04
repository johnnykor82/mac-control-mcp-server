# FR-025 — инвентаризация ошибок аргументов Mac Control MCP

Автоматически воспроизводимый аудит исходников и схем MCP; без вызова
инструментов, доступа к пользовательским аргументам и изменения production.

- Всего: **137** инструментов (108 frozen, 29 дополнительных).
- Опциональные background-инструменты зарегистрированы только в памяти.
- Статические исключения из 20 модулей: PermissionError=36, RuntimeError=36, TypeError=2, ValueError=137.
- Не классифицированных статических сообщений: **28**.
- Статические raise-сайты не являются доказательством ошибки параметра;
  ошибки среды, зависимости и после побочного эффекта проверяются отдельно.

## Семейства

| Семейство | Инструментов |
| --- | ---: |
| audit | 2 |
| background | 14 |
| chrome | 13 |
| custom | 2 |
| fs | 10 |
| git | 10 |
| gui | 13 |
| launchd | 2 |
| list | 1 |
| local | 1 |
| machine | 1 |
| mcp | 5 |
| network | 1 |
| package | 4 |
| process | 1 |
| project | 2 |
| read | 2 |
| restart | 1 |
| self | 2 |
| ssh | 17 |
| system | 1 |
| terminal | 8 |
| watcher | 22 |
| workspace | 1 |
| write | 1 |

## Реестр схем MCP

| Инструмент | Обязательные поля | Полей всего | Источник |
| --- | --- | ---: | --- |
| audit_search | — | 4 | additional |
| audit_tail | — | 1 | additional |
| background_app_action | action, element_path, expected_role, expected_title, session_token, window_ref | 8 | additional |
| background_app_capture | session_token, window_ref | 2 | additional |
| background_app_close | session_token | 1 | additional |
| background_app_create | bundle_id | 1 | additional |
| background_app_elements | session_token, window_ref | 4 | additional |
| background_app_list | — | 0 | additional |
| background_app_windows | session_token | 1 | additional |
| background_browser_action | action, session_token | 10 | additional |
| background_browser_capture | session_token | 3 | additional |
| background_browser_close | session_token | 1 | additional |
| background_browser_create | — | 2 | additional |
| background_browser_list | session_tokens | 1 | additional |
| background_browser_reopen | session_token | 1 | additional |
| background_browser_snapshot | session_token | 3 | additional |
| chrome_chat_adopt | task_id | 1 | frozen |
| chrome_chat_archive | task_id | 1 | frozen |
| chrome_chat_cleanup | — | 0 | frozen |
| chrome_chat_new | — | 2 | frozen |
| chrome_chat_read | — | 2 | frozen |
| chrome_chat_restore | task_id | 1 | frozen |
| chrome_chat_save | — | 2 | frozen |
| chrome_chat_send | — | 3 | frozen |
| chrome_chat_switch | task_id | 1 | frozen |
| chrome_chat_ui_status | — | 0 | frozen |
| chrome_chat_wait | — | 2 | frozen |
| chrome_orchestrator_launch | — | 0 | frozen |
| chrome_orchestrator_status | — | 0 | frozen |
| custom_command | operation | 2 | additional |
| custom_query | — | 2 | additional |
| fs_list | — | 3 | frozen |
| fs_mkdir | path, project | 2 | frozen |
| fs_move | destination, project, source | 3 | frozen |
| fs_read | path, project | 4 | frozen |
| fs_replace | expected_sha256, new, old, path, project | 5 | frozen |
| fs_restore | backup_id, path, project | 4 | frozen |
| fs_search | pattern, project | 4 | frozen |
| fs_stat | path, project | 3 | frozen |
| fs_trash | expected_sha256, path, project | 3 | frozen |
| fs_write | content, path, project | 4 | frozen |
| git_branches | project | 1 | frozen |
| git_commit | message, project | 2 | frozen |
| git_create_branch | name, project | 2 | frozen |
| git_diff | project | 3 | frozen |
| git_fetch | project | 1 | frozen |
| git_history | project | 2 | frozen |
| git_pull_ff | project | 1 | frozen |
| git_push | project | 1 | frozen |
| git_stage | paths, project | 2 | frozen |
| git_status | project | 2 | frozen |
| gui_displays | — | 0 | frozen |
| gui_focus | bundle_id | 1 | frozen |
| gui_mouse | action, x, y | 5 | frozen |
| gui_open_app | name | 1 | frozen |
| gui_press | key | 2 | frozen |
| gui_request_permissions | — | 0 | frozen |
| gui_screenshot | — | 2 | frozen |
| gui_scroll | — | 2 | frozen |
| gui_status | — | 0 | frozen |
| gui_tree | — | 3 | frozen |
| gui_type | text | 1 | frozen |
| gui_wait_title | title | 3 | frozen |
| gui_windows | — | 0 | frozen |
| launchd_restart | label | 1 | frozen |
| launchd_status | — | 1 | frozen |
| list_workspace | — | 2 | additional |
| local_http_probe | — | 3 | frozen |
| machine_health | — | 0 | frozen |
| mcp_bridge_call | target, tool | 5 | frozen |
| mcp_bridge_list | — | 2 | frozen |
| mcp_bridge_read | target, tool | 5 | frozen |
| mcp_diagnostics | — | 0 | additional |
| mcp_targets | — | 0 | frozen |
| network_listeners | — | 1 | frozen |
| package_capabilities | — | 0 | frozen |
| package_install | formula | 1 | frozen |
| package_installed | formula | 1 | frozen |
| package_job_status | job_id | 1 | frozen |
| process_snapshot | — | 1 | additional |
| project_roots | — | 0 | frozen |
| project_task | project, task | 3 | frozen |
| read_file | path | 1 | additional |
| read_service_log | name | 2 | additional |
| restart_server | — | 0 | additional |
| self_update_start | — | 1 | additional |
| self_update_status | — | 0 | additional |
| ssh_auth_diagnostics | — | 0 | frozen |
| ssh_diagnostic | host | 2 | frozen |
| ssh_download | host, local_path, remote_path | 5 | frozen |
| ssh_exec | command, host | 3 | frozen |
| ssh_identity_inspect | — | 1 | frozen |
| ssh_open | host | 1 | frozen |
| ssh_profile_approve_alias | name | 1 | frozen |
| ssh_profile_inventory | — | 0 | frozen |
| ssh_profile_register | host, name, user | 5 | frozen |
| ssh_pty_open | host | 1 | frozen |
| ssh_targets | — | 0 | frozen |
| ssh_transfer_begin | direction, host, remote_path | 10 | frozen |
| ssh_transfer_cancel | transfer_id | 1 | frozen |
| ssh_transfer_chunk | chunk_index, offset, transfer_id | 5 | frozen |
| ssh_transfer_finish | transfer_id | 2 | frozen |
| ssh_upload | host, local_path, remote_path | 6 | frozen |
| ssh_write_text | content, host, remote_path | 7 | frozen |
| system_info | — | 0 | additional |
| terminal_capabilities | — | 0 | frozen |
| terminal_close | session | 1 | frozen |
| terminal_exec | command | 3 | frozen |
| terminal_list | — | 0 | frozen |
| terminal_open | — | 3 | frozen |
| terminal_read | session | 2 | frozen |
| terminal_resize | session | 3 | frozen |
| terminal_send | session | 3 | frozen |
| watcher_ack_delivery | event_id, project_id | 2 | frozen |
| watcher_ack_wakeup | wakeup_id | 1 | frozen |
| watcher_cancel_wakeup | wakeup_id | 1 | frozen |
| watcher_dispatch_browser_task | executor_url, project_id, prompt, request_key, task_id | 5 | frozen |
| watcher_error_status | — | 1 | frozen |
| watcher_followup_browser_task | project_id, prompt, request_key, task_id | 4 | frozen |
| watcher_get_wakeup | wakeup_id | 1 | frozen |
| watcher_guide | — | 0 | frozen |
| watcher_list_wakeups | — | 1 | frozen |
| watcher_pause_project | project_id | 1 | frozen |
| watcher_read_report | project_id, task_id | 3 | frozen |
| watcher_read_result | project_id, task_id | 3 | frozen |
| watcher_register_browser_project | orchestrator_url, project_id | 2 | frozen |
| watcher_register_file_task | executor_url, project_id, task_id | 3 | frozen |
| watcher_register_project | orchestrator_url, project_id | 2 | frozen |
| watcher_register_task | executor_url, project_id, task_id | 3 | frozen |
| watcher_resolve_current_chat | evidence_text | 1 | frozen |
| watcher_resume_project | project_id | 1 | frozen |
| watcher_resume_task | capability_token, expected_revision, project_id, task_id | 4 | frozen |
| watcher_schedule_wakeup | delay_minutes, objective | 5 | frozen |
| watcher_status | — | 1 | frozen |
| watcher_submit_report | capability_token, content, project_id, revision, status, task_id | 6 | frozen |
| workspace_policy | — | 0 | additional |
| write_file | content, path | 3 | additional |

## Общие валидаторы вызываемых модулей

| Модуль | ValueError | PermissionError | RuntimeError | TypeError |
| --- | ---: | ---: | ---: | ---: |
| bridge_media.py | 11 | 11 | 0 | 0 |
| chrome_orchestrator_ops.py | 7 | 0 | 4 | 0 |
| command_plugins.py | 9 | 1 | 7 | 0 |
| fs_ops.py | 23 | 4 | 0 | 0 |
| git_ops.py | 8 | 1 | 0 | 0 |
| gui_ops.py | 9 | 0 | 5 | 0 |
| mcp_bridge_ops.py | 14 | 2 | 0 | 0 |
| package_ops.py | 4 | 0 | 2 | 0 |
| ssh_bridge_ops.py | 2 | 1 | 2 | 0 |
| ssh_manage_ops.py | 15 | 2 | 2 | 0 |
| system_ops.py | 8 | 2 | 0 | 0 |
| watcher_ops.py | 2 | 2 | 8 | 0 |
| maintenance_ops.py | 16 | 9 | 6 | 2 |
| background_browser_ops.py | 9 | 0 | 0 | 0 |
| background_native_ops.py | 0 | 1 | 0 | 0 |

## Backlog: необходима классификация

Не все сообщения являются ошибками аргументов; не предлагать
повтор без оценки этапа выполнения.

| Модуль | Сообщение |
| --- | --- |
| background_browser_ops.py | Invalid ChatBridge URL origin |
| background_browser_ops.py | Invalid browser session ID |
| background_browser_ops.py | Invalid browser session capability |
| background_browser_ops.py | Invalid client_request_id |
| bridge_media.py | Invalid downstream media encoding |
| bridge_media.py | Invalid media id |
| bridge_media.py | Unknown media storage type |
| chrome_orchestrator_ops.py | Invalid ChatBridge endpoint |
| chrome_orchestrator_ops.py | Invalid result filename |
| fs_ops.py | Invalid backup ID |
| fs_ops.py | Invalid trusted projects config |
| gui_ops.py | Invalid application name |
| maintenance_ops.py | Invalid path |
| mcp_bridge_ops.py | Invalid saved MCP targets |
| mcp_bridge_ops.py | Invalid stdio arguments |
| mcp_bridge_ops.py | Invalid stdio environment |
| mcp_bridge_ops.py | Invalid stdio working directory |
| ssh_bridge_ops.py | Invalid ssh_targets.json |
| ssh_bridge_ops.py | Unknown diagnostic command |
| ssh_manage_ops.py | Invalid SSH configuration |
| ssh_manage_ops.py | Invalid saved SSH alias |
| ssh_manage_ops.py | Invalid saved SSH host settings |
| ssh_manage_ops.py | Invalid saved SSH profile |
| ssh_manage_ops.py | Invalid saved SSH profile kind |
| ssh_manage_ops.py | Unknown profile type |
| system_ops.py | Invalid label |
| system_ops.py | Invalid launchd label |
| system_ops.py | Unsupported method or path |
