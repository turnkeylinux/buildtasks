LOG_LEVEL = 'DEBUG'

KERNELS = {
    # http://go.alonswartz.org/aws-kernels (pv-grub-hd00_1.04)
    'us-east-1': {'amd64': 'aki-499ccb20', 'i386': 'aki-659ccb0c'},
    'us-west-1': {'amd64': 'aki-920531d7', 'i386': 'aki-960531d3'},
    'us-west-2': {'amd64': 'aki-e28f11d2', 'i386': 'aki-e68f11d6'},
    'sa-east-1': {'amd64': 'aki-5153f44c', 'i386': 'aki-5753f44a'},
    'eu-west-1': {'amd64': 'aki-58a3452f', 'i386': 'aki-5ea34529'},
    'ap-southeast-1': {'amd64': 'aki-563e7404', 'i386': 'aki-5e3e740c'},
    'ap-southeast-2': {'amd64': 'aki-3b1d8001', 'i386': 'aki-c162fffb'},
    'ap-northeast-1': {'amd64': 'aki-196bf518', 'i386': 'aki-1f6bf51e'},
}

