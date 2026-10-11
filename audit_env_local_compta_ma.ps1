cd 'C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma'

powershell -ExecutionPolicy Bypass `
  -File .\audit_env_local_compta_ma.ps1 `
  -ProjectRoot . `
  -OutputFile "$env:TEMP\AUDIT_ENV_LOCAL_COMPTA_MA.txt"