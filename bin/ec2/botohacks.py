import conf

from boto.regioninfo import RegionInfo
from boto.ec2.connection import EC2Connection
from boto.ec2 import RegionData

class _EC2Connection(EC2Connection):
    def modify_image_attribute(self, image_id, attribute='launchPermission',
                               operation='add', user_ids=None, groups=None,
                               product_codes=None):
        """
        Changes an attribute of an image.

        :type image_id: string
        :param image_id: The image id you wish to change

        :type attribute: string
        :param attribute: The attribute you wish to change

        :type operation: string
        :param operation: Either add or remove (this is required for changing
            launchPermissions)

        :type user_ids: list
        :param user_ids: The Amazon IDs of users to add/remove attributes

        :type groups: list
        :param groups: The groups to add/remove attributes

        :type product_codes: list
        :param product_codes: Amazon DevPay product code. Currently only one
            product code can be associated with an AMI. Once
            set, the product code cannot be changed or reset.
        """
        params = {'ImageId': image_id,
                  'Attribute': attribute,
                  'OperationType': operation}
        if user_ids:
            self.build_list_params(params, user_ids, 'UserId')
        if groups:
            self.build_list_params(params, groups, 'UserGroup')
        if product_codes:
            self.build_list_params(params, product_codes, 'ProductCode')
        return self.get_status('ModifyImageAttribute', params, verb='POST')

def connect(region_name):
    region = RegionInfo(
        name=region_name,
        endpoint=RegionData[region_name],
        connection_cls=_EC2Connection)

    return region.connect(
        aws_access_key_id=conf.SMP_ACCESSKEY,
        aws_secret_access_key=conf.SMP_SECRETKEY)
