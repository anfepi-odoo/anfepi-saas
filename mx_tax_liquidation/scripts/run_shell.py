import subprocess
result = subprocess.run(
    ['/opt/odoo/odoo-core/odoo-bin', 'shell', '-d', 'odoo17', '-c', '/etc/odoo/odoo.conf', '--no-http'],
    stdin=open('/mnt/benotto-addons/mx_tax_liquidation/scripts/sim_vendor_bills.py'),
    capture_output=True, text=True, timeout=180
)
print('EXIT:', result.returncode)
if result.stdout:
    for line in result.stdout.split('\n'):
        if line.strip():
            print(line)
else:
    print('NO STDOUT')
errs = [l for l in result.stderr.split('\n') if 'ERROR' in l or 'Traceback' in l or 'Exception' in l or 'ValueError' in l]
if errs:
    print('STDERR ERRORS:')
    print('\n'.join(errs[-20:]))
