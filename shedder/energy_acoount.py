
###################################################################
#
#
class EnergyAccount:
    def __init(self, max_energy):

        self.max_energy=max_energy
        self.acc_energy
        self.estimated_energy
        self.power
        self.power_1min = [0 for n in range(0,60)]
        self.power_10min = [0 for n in range(0,6)]
        self.power_15min = [0 for n in range(0,4)]




        # Loop 1:
#     Les total effekt
#     Les total energy
#     Les ladeeffekt
#     Akkumuler energi for visning
#     Akkumuler effekt / min

#     * P Gjenomsnitt hittil i timen
#     * P Gjennomsnitt momentant
    

# Loop 2
#     juster opp/ned effekt til effekt / min <= 10 kw