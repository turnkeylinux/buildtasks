LOG_LEVEL = 'DEBUG'

KERNELS = {
    # http://go.alonswartz.org/aws-kernels (pv-grub-hd0_1.03)
    'us-east-1': {'amd64': 'aki-88aa75e1', 'i386': 'aki-b6aa75df'},
    'us-west-1': {'amd64': 'aki-f77e26b2', 'i386': 'aki-f57e26b0'},
    'us-west-2': {'amd64': 'aki-fc37bacc', 'i386': 'aki-fa37baca'},
    'eu-west-1': {'amd64': 'aki-71665e05', 'i386': 'aki-75665e01'},
    'sa-east-1': {'amd64': 'aki-c48f51d9', 'i386': 'aki-ca8f51d7'},
    'ap-southeast-1': {'amd64': 'aki-fe1354ac', 'i386': 'aki-f81354aa'},
    'ap-southeast-2': {'amd64': 'aki-31990e0b', 'i386': 'aki-33990e09'},
    'ap-northeast-1': {'amd64': 'aki-44992845', 'i386': 'aki-42992843'},
}
