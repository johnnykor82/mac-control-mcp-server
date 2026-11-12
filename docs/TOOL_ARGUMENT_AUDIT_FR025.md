# FR-025 — инвентаризация ошибок аргументов Mac Control MCP

Автоматически воспроизводимый аудит исходников и схем MCP; без вызова
инструментов, доступа к пользовательским аргументам и изменения production.

- Всего: **142** инструментов (112 frozen, 30 дополнительных).
- Опциональные background-инструменты зарегистрированы только в памяти.
- Статические исключения из 20 модулей: PermissionError=37, RuntimeError=35, TypeError=2, ValueError=139.
- Не классифицированных статических сообщений: **30**.
- Статические raise-сайты не являются доказательством ошибки параметра;
  ошибки среды, зависимости и после побочного эффекта проверяются отдельно.

## Семейства

| Семейство | Инструментов |
| --- | ---: |
| audit | 2 |
| background | 14 |
| chat | 1 |
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
| watcher | 26 |
| workspace | 1 |
| write | 1 |

## Реестр схем MCP

| Инструмент | Обязательные поля | Полей всего | Источник |
| --- | --- | ---: | --- |
| audit_search | audit_context | 5 | additional |
| audit_tail | audit_context | 2 | additional |
| background_app_action | action, audit_context, element_path, expected_role, expected_title, session_token, window_ref | 9 | additional |
| background_app_capture | audit_context, session_token, window_ref | 3 | additional |
| background_app_close | audit_context, session_token | 2 | additional |
| background_app_create | audit_context, bundle_id | 2 | additional |
| background_app_elements | audit_context, session_token, window_ref | 5 | additional |
| background_app_list | audit_context | 1 | additional |
| background_app_windows | audit_context, session_token | 2 | additional |
| background_browser_action | action, audit_context, session_token | 11 | additional |
| background_browser_capture | audit_context, session_token | 4 | additional |
| background_browser_close | audit_context, session_token | 2 | additional |
| background_browser_create | audit_context | 3 | additional |
| background_browser_list | audit_context, session_tokens | 2 | additional |
| background_browser_reopen | audit_context, session_token | 2 | additional |
| background_browser_snapshot | audit_context, session_token | 4 | additional |
| chat_marker_issue | audit_context | 1 | additional |
| chrome_chat_adopt | audit_context, task_id | 2 | frozen |
| chrome_chat_archive | audit_context, task_id | 2 | frozen |
| chrome_chat_cleanup | audit_context | 1 | frozen |
| chrome_chat_new | audit_context | 3 | frozen |
| chrome_chat_read | audit_context | 3 | frozen |
| chrome_chat_restore | audit_context, task_id | 2 | frozen |
| chrome_chat_save | audit_context | 3 | frozen |
| chrome_chat_send | audit_context | 4 | frozen |
| chrome_chat_switch | audit_context, task_id | 2 | frozen |
| chrome_chat_ui_status | audit_context | 1 | frozen |
| chrome_chat_wait | audit_context | 3 | frozen |
| chrome_orchestrator_launch | audit_context | 1 | frozen |
| chrome_orchestrator_status | audit_context | 1 | frozen |
| custom_command | audit_context, operation | 3 | additional |
| custom_query | audit_context | 3 | additional |
| fs_list | audit_context | 4 | frozen |
| fs_mkdir | audit_context, path, project | 3 | frozen |
| fs_move | audit_context, destination, project, source | 4 | frozen |
| fs_read | audit_context, path, project | 5 | frozen |
| fs_replace | audit_context, expected_sha256, new, old, path, project | 6 | frozen |
| fs_restore | audit_context, backup_id, path, project | 5 | frozen |
| fs_search | audit_context, pattern, project | 5 | frozen |
| fs_stat | audit_context, path, project | 4 | frozen |
| fs_trash | audit_context, expected_sha256, path, project | 4 | frozen |
| fs_write | audit_context, content, path, project | 5 | frozen |
| git_branches | audit_context, project | 2 | frozen |
| git_commit | audit_context, message, project | 3 | frozen |
| git_create_branch | audit_context, name, project | 3 | frozen |
| git_diff | audit_context, project | 4 | frozen |
| git_fetch | audit_context, project | 2 | frozen |
| git_history | audit_context, project | 3 | frozen |
| git_pull_ff | audit_context, project | 2 | frozen |
| git_push | audit_context, project | 2 | frozen |
| git_stage | audit_context, paths, project | 3 | frozen |
| git_status | audit_context, project | 3 | frozen |
| gui_displays | audit_context | 1 | frozen |
| gui_focus | audit_context, bundle_id | 2 | frozen |
| gui_mouse | action, audit_context, x, y | 6 | frozen |
| gui_open_app | audit_context, name | 2 | frozen |
| gui_press | audit_context, key | 3 | frozen |
| gui_request_permissions | audit_context | 1 | frozen |
| gui_screenshot | audit_context | 3 | frozen |
| gui_scroll | audit_context | 3 | frozen |
| gui_status | audit_context | 1 | frozen |
| gui_tree | audit_context | 4 | frozen |
| gui_type | audit_context, text | 2 | frozen |
| gui_wait_title | audit_context, title | 4 | frozen |
| gui_windows | audit_context | 1 | frozen |
| launchd_restart | audit_context, label | 2 | frozen |
| launchd_status | audit_context | 2 | frozen |
| list_workspace | audit_context | 3 | additional |
| local_http_probe | audit_context | 4 | frozen |
| machine_health | audit_context | 1 | frozen |
| mcp_bridge_call | audit_context, target, tool | 6 | frozen |
| mcp_bridge_list | audit_context | 3 | frozen |
| mcp_bridge_read | audit_context, target, tool | 6 | frozen |
| mcp_diagnostics | audit_context | 1 | additional |
| mcp_targets | audit_context | 1 | frozen |
| network_listeners | audit_context | 2 | frozen |
| package_capabilities | audit_context | 1 | frozen |
| package_install | audit_context, formula | 2 | frozen |
| package_installed | audit_context, formula | 2 | frozen |
| package_job_status | audit_context, job_id | 2 | frozen |
| process_snapshot | audit_context | 2 | additional |
| project_roots | audit_context | 1 | frozen |
| project_task | audit_context, project, task | 4 | frozen |
| read_file | audit_context, path | 2 | additional |
| read_service_log | audit_context, name | 3 | additional |
| restart_server | audit_context | 1 | additional |
| self_update_start | audit_context | 2 | additional |
| self_update_status | audit_context | 1 | additional |
| ssh_auth_diagnostics | audit_context | 1 | frozen |
| ssh_diagnostic | audit_context, host | 3 | frozen |
| ssh_download | audit_context, host, local_path, remote_path | 6 | frozen |
| ssh_exec | audit_context, command, host | 4 | frozen |
| ssh_identity_inspect | audit_context | 2 | frozen |
| ssh_open | audit_context, host | 2 | frozen |
| ssh_profile_approve_alias | audit_context, name | 2 | frozen |
| ssh_profile_inventory | audit_context | 1 | frozen |
| ssh_profile_register | audit_context, host, name, user | 6 | frozen |
| ssh_pty_open | audit_context, host | 2 | frozen |
| ssh_targets | audit_context | 1 | frozen |
| ssh_transfer_begin | audit_context, direction, host, remote_path | 11 | frozen |
| ssh_transfer_cancel | audit_context, transfer_id | 2 | frozen |
| ssh_transfer_chunk | audit_context, chunk_index, offset, transfer_id | 6 | frozen |
| ssh_transfer_finish | audit_context, transfer_id | 3 | frozen |
| ssh_upload | audit_context, host, local_path, remote_path | 7 | frozen |
| ssh_write_text | audit_context, content, host, remote_path | 8 | frozen |
| system_info | audit_context | 1 | additional |
| terminal_capabilities | audit_context | 1 | frozen |
| terminal_close | audit_context, session | 2 | frozen |
| terminal_exec | audit_context, command | 4 | frozen |
| terminal_list | audit_context | 1 | frozen |
| terminal_open | audit_context | 4 | frozen |
| terminal_read | audit_context, session | 3 | frozen |
| terminal_resize | audit_context, session | 4 | frozen |
| terminal_send | audit_context, session | 4 | frozen |
| watcher_ack_delivery | audit_context, event_id, project_id | 3 | frozen |
| watcher_ack_wakeup | audit_context, wakeup_id | 2 | frozen |
| watcher_approve_goal | audit_context, expected_revision, project_id, task_id | 4 | frozen |
| watcher_cancel_wakeup | audit_context, wakeup_id | 2 | frozen |
| watcher_dispatch_browser_task | audit_context, executor_url, project_id, prompt, request_key, task_id | 6 | frozen |
| watcher_error_status | audit_context | 2 | frozen |
| watcher_followup_browser_task | audit_context, project_id, prompt, request_key, task_id | 5 | frozen |
| watcher_get_wakeup | audit_context, wakeup_id | 2 | frozen |
| watcher_guide | audit_context | 1 | frozen |
| watcher_list_wakeups | audit_context | 2 | frozen |
| watcher_pause_project | audit_context, project_id | 2 | frozen |
| watcher_read_report | audit_context, project_id, task_id | 4 | frozen |
| watcher_read_result | audit_context, project_id, task_id | 4 | frozen |
| watcher_reconcile_goal_review | audit_context, project_id, task_id | 3 | frozen |
| watcher_register_browser_project | audit_context, orchestrator_url, project_id | 3 | frozen |
| watcher_register_file_task | audit_context, executor_url, project_id, task_id | 4 | frozen |
| watcher_register_project | audit_context, orchestrator_url, project_id | 3 | frozen |
| watcher_register_task | audit_context, executor_url, project_id, task_id | 4 | frozen |
| watcher_resolve_current_chat | audit_context, evidence_text | 2 | frozen |
| watcher_resume_project | audit_context, project_id | 2 | frozen |
| watcher_resume_task | audit_context, capability_token, expected_revision, project_id, task_id | 5 | frozen |
| watcher_return_for_rework | audit_context, expected_revision, instruction, project_id, request_key, task_id | 6 | frozen |
| watcher_schedule_wakeup | audit_context, delay_minutes, objective | 6 | frozen |
| watcher_spawn_subagent | audit_context, orchestrator_marker, project_id, prompt, request_key, task_id | 10 | frozen |
| watcher_status | audit_context | 2 | frozen |
| watcher_submit_report | audit_context, capability_token, content, project_id, revision, status, task_id | 7 | frozen |
| workspace_policy | audit_context | 1 | additional |
| write_file | audit_context, content, path | 4 | additional |

## Общие валидаторы вызываемых модулей

| Модуль | ValueError | PermissionError | RuntimeError | TypeError |
| --- | ---: | ---: | ---: | ---: |
| bridge_media.py | 11 | 11 | 0 | 0 |
| chrome_orchestrator_ops.py | 7 | 0 | 4 | 0 |
| command_plugins.py | 9 | 1 | 7 | 0 |
| fs_ops.py | 23 | 4 | 0 | 0 |
| git_ops.py | 8 | 1 | 0 | 0 |
| gui_ops.py | 11 | 0 | 4 | 0 |
| mcp_bridge_ops.py | 14 | 2 | 0 | 0 |
| package_ops.py | 4 | 0 | 2 | 0 |
| ssh_bridge_ops.py | 2 | 1 | 2 | 0 |
| ssh_manage_ops.py | 15 | 2 | 2 | 0 |
| system_ops.py | 8 | 2 | 0 | 0 |
| watcher_ops.py | 2 | 3 | 8 | 0 |
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
| gui_ops.py | Invalid or oversized screenshot JPEG |
| gui_ops.py | Invalid screenshot JPEG base64 |
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
